"""Proxmox VE collector — a PVE cluster via the REST API (read-only).

Ported from the opsview Proxmox enumerator. It enumerates every cluster node, then every
QEMU VM (NodeKind.VM) and LXC container (NodeKind.CONTAINER), mapping each onto the unified
`Node` model. Compute, disks, NICs and pool->tags come straight from each guest's config;
the primary IP comes from the QEMU guest agent (best-effort) or a static LXC net config.

Auth mirrors PVE itself:
  - **API token (recommended):** pass ``token_id`` (``user@realm!tokenid``) + ``token_secret``;
    we send a ``PVEAPIToken`` Authorization header — no login round-trip.
  - **Login ticket:** pass ``username`` (``user@realm``) + ``password``; we exchange them for a
    ticket at ``/access/ticket``.

A read-only role (e.g. PVEAuditor on /) is sufficient — this collector only issues GETs.
``requests`` is imported lazily so the rest of FleetView works without it installed.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ...models import (
    Compute,
    Disk,
    DiskType,
    Nic,
    Node,
    NodeKind,
    OSFamily,
    OSInfo,
    Placement,
    PowerState,
    Provider,
    ProviderKind,
    SourceRef,
)
from ..base import Collector, CollectorError, CollectResult

# config keys that hold a virtual disk (e.g. scsi0, virtio1, sata2, ide0)
_DISK_KEY_RE = re.compile(r"^(scsi|virtio|sata|ide)\d+$")
# LXC rootfs / mountpoint keys (rootfs, mp0, mp1, ...)
_LXC_DISK_KEY_RE = re.compile(r"^(rootfs|mp\d+)$")
_SIZE_UNITS = {"K": 1, "M": 1024, "G": 1024 * 1024, "T": 1024 * 1024 * 1024}  # -> KiB

_TIMEOUT = 15


def _size_to_kb(sz: str) -> int:
    """Parse a PVE size token ('32G', '512M', '1T') to KiB."""
    sz = (sz or "").strip()
    if sz and sz[-1].upper() in _SIZE_UNITS:
        try:
            return int(float(sz[:-1]) * _SIZE_UNITS[sz[-1].upper()])
        except ValueError:
            return 0
    try:
        return int(int(sz) / 1024)  # bare bytes
    except ValueError:
        return 0


class ProxmoxCollector(Collector):
    provider_kind = ProviderKind.PROXMOX

    def __init__(
        self,
        host: str,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        port: int = 8006,
        verify_ssl: bool = True,
    ) -> None:
        self.host = host
        self.token_id = token_id
        self.token_secret = token_secret
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self._session: Any = None

    # ----------------------------------------------------------------- connection

    @property
    def _api_base(self) -> str:
        return f"https://{self.host}:{self.port}/api2/json"

    def _connect(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            import requests  # type: ignore
        except ImportError as exc:
            raise CollectorError(
                "requests is not installed. Install with: pip install 'fleetview[proxmox]'"
            ) from exc

        sess = requests.Session()
        sess.verify = self.verify_ssl
        if not self.verify_ssl:
            try:
                from urllib3.exceptions import InsecureRequestWarning  # type: ignore

                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            except Exception:
                pass

        if self.token_id and self.token_secret:
            # API token — no login round-trip needed.
            sess.headers["Authorization"] = f"PVEAPIToken={self.token_id}={self.token_secret}"
        elif self.username and self.password:
            # Username/password — exchange for a ticket cookie.
            try:
                r = sess.post(
                    f"{self._api_base}/access/ticket",
                    data={"username": self.username, "password": self.password},
                    timeout=_TIMEOUT,
                )
            except Exception as exc:
                raise CollectorError(
                    f"Failed to connect to Proxmox {self.host}: {exc}"
                ) from exc
            if r.status_code != 200:
                raise CollectorError(
                    f"Proxmox login failed for {self.host} (HTTP {r.status_code})"
                )
            data = (r.json() or {}).get("data") or {}
            ticket = data.get("ticket")
            if not ticket:
                raise CollectorError(f"Proxmox login to {self.host} returned no ticket")
            sess.cookies.set("PVEAuthCookie", ticket)
            if data.get("CSRFPreventionToken"):
                sess.headers["CSRFPreventionToken"] = data["CSRFPreventionToken"]
        else:
            raise CollectorError(
                "Proxmox requires either an API token (token_id + token_secret) or "
                "a login (username + password)"
            )

        self._session = sess
        return sess

    def _get(self, path: str, **kwargs: Any) -> Any:
        """GET a PVE endpoint and return the unwrapped 'data' payload (or None)."""
        sess = self._connect()
        r = sess.get(f"{self._api_base}{path}", timeout=_TIMEOUT, **kwargs)
        if r.status_code == 403:
            raise CollectorError(
                "Proxmox permission denied — the credential needs at least PVEAuditor on /"
            )
        if r.status_code != 200:
            raise CollectorError(f"Proxmox GET {path} failed (HTTP {r.status_code})")
        return (r.json() or {}).get("data")

    def test_connection(self) -> bool:
        # /version is readable by any authenticated user; cheapest connectivity check.
        data = self._get("/version")
        return bool(data)

    # ----------------------------------------------------------------- collection

    def collect(self) -> CollectResult:
        self._connect()

        version = {}
        try:
            version = self._get("/version") or {}
        except Exception:
            pass

        provider = Provider(
            kind=ProviderKind.PROXMOX,
            instance=self.host,
            display_name=self.host,
            endpoint=f"https://{self.host}:{self.port}",
            extra={k: v for k, v in version.items() if v is not None},
        )

        warnings: list[str] = []
        nodes: list[Node] = []

        # Enumerate cluster nodes (best-effort, informational).
        cluster_nodes: list[str] = []
        try:
            for n in self._get("/nodes") or []:
                name = n.get("node")
                if name:
                    cluster_nodes.append(name)
        except Exception as exc:
            warnings.append(f"Failed to enumerate Proxmox nodes: {exc}")
        provider.extra["cluster_nodes"] = cluster_nodes

        # Enumerate all QEMU VMs + LXC containers across the cluster.
        try:
            resources = self._get("/cluster/resources", params={"type": "vm"}) or []
        except CollectorError:
            raise
        except Exception as exc:
            raise CollectorError(f"Proxmox cluster/resources failed: {exc}") from exc

        for res in resources:
            vmtype = res.get("type")  # "qemu" or "lxc"
            if vmtype not in ("qemu", "lxc"):
                continue
            try:
                nodes.append(self._guest_to_node(res, vmtype))
            except Exception as exc:  # never let one bad guest kill the whole scan
                name = res.get("name") or res.get("vmid") or "<unknown>"
                warnings.append(f"Failed to map Proxmox guest '{name}': {exc}")

        provider.node_count = len(nodes)
        return CollectResult(provider=provider, nodes=nodes, warnings=warnings)

    # ----------------------------------------------------------------- mapping

    def _guest_to_node(self, res: dict, vmtype: str) -> Node:
        vmid = res.get("vmid")
        pve_node = res.get("node")
        name = res.get("name") or f"{vmtype}-{vmid}"
        status = res.get("status")

        cfg: dict = {}
        try:
            cfg = self._get(f"/nodes/{pve_node}/{vmtype}/{vmid}/config") or {}
        except Exception:
            cfg = {}

        kind = NodeKind.VM if vmtype == "qemu" else NodeKind.CONTAINER
        native_id = str(vmid)
        node_id = self.make_node_id(ProviderKind.PROXMOX, self.host, native_id)

        power = PowerState.RUNNING if status == "running" else PowerState.STOPPED
        if status == "paused" or status == "suspended":
            power = PowerState.SUSPENDED

        placement = Placement(
            provider=ProviderKind.PROXMOX,
            host=pve_node,
            cluster=res.get("pool") or None,
            resource_pool=res.get("pool") or None,
            datacenter="Proxmox",
            zone=pve_node,
        )

        compute = self._compute(res, cfg)
        disks = self._disks(cfg, vmtype)
        nics = self._nics(cfg)

        # Primary IP: QEMU guest agent (running only), else static LXC net config.
        primary_ip = None
        if vmtype == "lxc":
            primary_ip = self._ipv4_from_lxc_config(cfg)
        if primary_ip is None and vmtype == "qemu" and status == "running":
            primary_ip = self._ipv4_from_agent(pve_node, vmid)
        if primary_ip and nics:
            if primary_ip not in nics[0].ips:
                nics[0].ips.insert(0, primary_ip)
        elif primary_ip:
            nics.append(Nic(label="net0", ips=[primary_ip]))

        os_info = self._os(cfg, vmtype)

        tags: dict[str, str] = {}
        pool = res.get("pool")
        if pool:
            tags["pool"] = str(pool)
        # PVE per-guest tags are a semicolon/comma-separated string in config.
        raw_tags = cfg.get("tags")
        if isinstance(raw_tags, str):
            for t in re.split(r"[;,]", raw_tags):
                t = t.strip()
                if t:
                    tags[f"tag:{t}"] = "true"

        return Node(
            id=node_id,
            name=name,
            kind=kind,
            power_state=power,
            placement=placement,
            compute=compute,
            disks=disks,
            nics=nics,
            os=os_info,
            tags=tags,
            annotations=cfg.get("description") or None,
            source=SourceRef(
                provider=ProviderKind.PROXMOX,
                provider_instance=self.host,
                native_id=native_id,
                native_type=vmtype,
                raw=self._raw(res, cfg),
            ),
        )

    # ----------------------------------------------------------------- helpers

    def _compute(self, res: dict, cfg: dict) -> Compute:
        # cluster/resources gives maxcpu/maxmem; config gives the requested shape.
        vcpus = cfg.get("cores") or cfg.get("vcpus") or res.get("maxcpu")
        sockets = cfg.get("sockets")
        cores = cfg.get("cores")
        if cores and sockets:
            vcpus = int(cores) * int(sockets)
        try:
            vcpus = int(vcpus) if vcpus is not None else None
        except (TypeError, ValueError):
            vcpus = None

        # memory: config 'memory' is MiB; cluster maxmem is bytes.
        mem_mb: Optional[int] = None
        if cfg.get("memory") is not None:
            try:
                mem_mb = int(cfg["memory"])
            except (TypeError, ValueError):
                mem_mb = None
        elif res.get("maxmem"):
            try:
                mem_mb = int(int(res["maxmem"]) / (1024 * 1024))
            except (TypeError, ValueError):
                mem_mb = None

        return Compute(
            vcpus=vcpus,
            cores_per_socket=int(cores) if cores else None,
            sockets=int(sockets) if sockets else None,
            memory_mb=mem_mb,
            architecture="x86_64",
            firmware=cfg.get("bios"),  # 'seabios' | 'ovmf' for qemu; None for lxc
        )

    def _disks(self, cfg: dict, vmtype: str) -> list[Disk]:
        disks: list[Disk] = []
        key_re = _DISK_KEY_RE if vmtype == "qemu" else _LXC_DISK_KEY_RE
        for key, val in cfg.items():
            if not key_re.match(key) or not isinstance(val, str):
                continue
            if "media=cdrom" in val:
                continue
            size_kb = self._disk_size_kb(val)
            backing = val.split(",")[0].split(":")[0] or None  # storage pool id
            path = val.split(",")[0] or None
            provisioning = None
            if ",backup=" in val or "discard=on" in val:
                provisioning = "thin"
            disks.append(
                Disk(
                    label=key,
                    size_gb=round(size_kb / 1024 / 1024, 2) if size_kb else None,
                    disk_type=DiskType.UNKNOWN,
                    backing=backing,
                    path=path,
                    provisioning=provisioning,
                )
            )
        return disks

    @staticmethod
    def _disk_size_kb(cfg_value: str) -> int:
        for part in (cfg_value or "").split(","):
            if part.startswith("size="):
                return _size_to_kb(part[len("size="):])
        return 0

    def _nics(self, cfg: dict) -> list[Nic]:
        nics: list[Nic] = []
        for key in sorted(k for k in cfg if k.startswith("net") and k[3:].isdigit()):
            val = cfg.get(key)
            if not isinstance(val, str):
                continue
            mac = None
            bridge = None
            vlan = None
            for part in val.split(","):
                part = part.strip()
                if "=" not in part:
                    # leading "virtio=AA:BB:.." style (model=mac)
                    continue
                k, _, v = part.partition("=")
                k = k.lower()
                if k in ("virtio", "e1000", "rtl8139", "vmxnet3", "hwaddr", "macaddr"):
                    mac = v
                elif k == "bridge":
                    bridge = v
                elif k == "tag":
                    try:
                        vlan = int(v)
                    except ValueError:
                        vlan = None
            nics.append(
                Nic(
                    label=key,
                    mac=mac,
                    network=bridge,
                    vlan=vlan,
                )
            )
        return nics

    def _ipv4_from_agent(self, pve_node: str, vmid: Any) -> Optional[str]:
        """Best-effort first non-loopback IPv4 from the QEMU guest agent."""
        try:
            result = self._get(
                f"/nodes/{pve_node}/qemu/{vmid}/agent/network-get-interfaces"
            )
        except Exception:
            return None
        if isinstance(result, dict):
            result = result.get("result") or []
        for iface in result or []:
            for addr in iface.get("ip-addresses") or []:
                ip = addr.get("ip-address", "")
                if addr.get("ip-address-type") == "ipv4" and not ip.startswith(
                    ("127.", "169.254.", "0.")
                ):
                    return ip
        return None

    @staticmethod
    def _ipv4_from_lxc_config(cfg: dict) -> Optional[str]:
        """Parse a static IPv4 out of an LXC config's netN strings."""
        for key, val in cfg.items():
            if not key.startswith("net") or not isinstance(val, str):
                continue
            for part in val.split(","):
                if part.startswith("ip="):
                    ip = part[3:].split("/")[0]
                    if ip and ip.lower() != "dhcp" and not ip.startswith(
                        ("127.", "169.254.")
                    ):
                        return ip
        return None

    def _os(self, cfg: dict, vmtype: str) -> OSInfo:
        ostype = cfg.get("ostype", "")
        family = OSFamily.UNKNOWN
        distro = None
        if vmtype == "lxc":
            family = OSFamily.LINUX
            distro = ostype or "container"
        else:
            o = (ostype or "").lower()
            if o in ("l24", "l26"):
                family = OSFamily.LINUX
            elif o.startswith("w"):
                family = OSFamily.WINDOWS
            elif o in ("solaris",):
                family = OSFamily.OTHER
            distro = ostype or None
        return OSInfo(
            family=family,
            distro=distro,
            hostname=cfg.get("hostname") or cfg.get("name"),
        )

    @staticmethod
    def _raw(res: dict, cfg: dict) -> dict:
        return {
            "resource": {k: v for k, v in res.items() if v is not None},
            "config": cfg,
        }
