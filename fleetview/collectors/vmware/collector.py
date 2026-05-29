"""VMware collector — vCenter or standalone ESXi, via pyVmomi (read-only).

Maps each VirtualMachine onto the unified `Node` model. At the hypervisor layer we get a lot
for free: compute shape, disks + their datastores, NICs + port groups, power state, and (when
VMware Tools is installed) guest OS, hostname, and IP addresses. Deep in-guest software and
data-flow discovery is a later milestone; the hypervisor view is the foundation.

pyVmomi is imported lazily so the rest of FleetView works without it installed.
"""
from __future__ import annotations

import ssl
from typing import Any, Optional

from ...models import (
    Compute,
    Disk,
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

_POWER_MAP = {
    "poweredOn": PowerState.RUNNING,
    "poweredOff": PowerState.STOPPED,
    "suspended": PowerState.SUSPENDED,
}

_GUEST_FAMILY_MAP = {
    "linuxGuest": OSFamily.LINUX,
    "windowsGuest": OSFamily.WINDOWS,
    "netwareGuest": OSFamily.OTHER,
    "solarisGuest": OSFamily.OTHER,
    "darwinGuest": OSFamily.OTHER,
    "otherGuestFamily": OSFamily.OTHER,
}


class VMwareCollector(Collector):
    provider_kind = ProviderKind.VMWARE

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = True,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self._si: Any = None  # ServiceInstance

    # ----------------------------------------------------------------- connection

    def _connect(self) -> Any:
        if self._si is not None:
            return self._si
        try:
            from pyVim.connect import SmartConnect  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise CollectorError(
                "pyVmomi is not installed. Install with: pip install 'fleetview[vmware]'"
            ) from exc

        ctx: Optional[ssl.SSLContext] = None
        if not self.verify_ssl:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        try:
            self._si = SmartConnect(
                host=self.host,
                user=self.username,
                pwd=self.password,
                port=self.port,
                sslContext=ctx,
            )
        except Exception as exc:  # pyVmomi raises a variety of types
            raise CollectorError(f"Failed to connect to vCenter/ESXi {self.host}: {exc}") from exc
        return self._si

    def test_connection(self) -> bool:
        si = self._connect()
        about = si.content.about
        return bool(about and about.fullName)

    # ----------------------------------------------------------------- collection

    def collect(self) -> CollectResult:
        from pyVmomi import vim  # type: ignore

        si = self._connect()
        content = si.content
        about = content.about

        provider = Provider(
            kind=ProviderKind.VMWARE,
            instance=self.host,
            display_name=getattr(about, "name", None),
            endpoint=f"https://{self.host}:{self.port}",
            extra={
                "full_name": getattr(about, "fullName", None),
                "version": getattr(about, "version", None),
                "build": getattr(about, "build", None),
                "api_type": getattr(about, "apiType", None),
            },
        )

        warnings: list[str] = []
        nodes: list[Node] = []

        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            for vm in view.view:
                try:
                    nodes.append(self._vm_to_node(vm, vim))
                except Exception as exc:  # never let one bad VM kill the whole scan
                    name = getattr(vm, "name", "<unknown>")
                    warnings.append(f"Failed to map VM '{name}': {exc}")
        finally:
            view.Destroy()

        provider.node_count = len(nodes)
        return CollectResult(provider=provider, nodes=nodes, warnings=warnings)

    # ----------------------------------------------------------------- mapping

    def _vm_to_node(self, vm: Any, vim: Any) -> Node:
        config = getattr(vm, "config", None)
        runtime = getattr(vm, "runtime", None)
        guest = getattr(vm, "guest", None)
        summary = getattr(vm, "summary", None)

        native_id = vm._moId
        node_id = self.make_node_id(ProviderKind.VMWARE, self.host, native_id)

        name = getattr(config, "name", None) or getattr(vm, "name", native_id)
        is_template = bool(getattr(config, "template", False))

        power = PowerState.UNKNOWN
        host_name = None
        if runtime is not None:
            power = _POWER_MAP.get(str(getattr(runtime, "powerState", "")), PowerState.UNKNOWN)
            host_obj = getattr(runtime, "host", None)
            if host_obj is not None:
                host_name = getattr(host_obj, "name", None)

        placement = Placement(
            provider=ProviderKind.VMWARE,
            host=host_name,
            cluster=self._cluster_of(runtime),
            resource_pool=self._name_of(getattr(vm, "resourcePool", None)),
            datacenter=self._datacenter_of(vm),
            folder=self._folder_path(vm),
        )

        compute = self._compute(config)
        disks, nics = self._devices(config, guest, vim)
        os_info = self._os(config, guest)

        node = Node(
            id=node_id,
            name=name,
            kind=NodeKind.VM,
            power_state=power,
            placement=placement,
            compute=compute,
            disks=disks,
            nics=nics,
            os=os_info,
            tags=self._tags(vm),
            annotations=getattr(config, "annotation", None) or None,
            source=SourceRef(
                provider=ProviderKind.VMWARE,
                provider_instance=self.host,
                native_id=native_id,
                native_type="VirtualMachine",
                raw=self._raw(config, runtime, summary, is_template),
            ),
        )
        return node

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _name_of(obj: Any) -> Optional[str]:
        return getattr(obj, "name", None) if obj is not None else None

    def _cluster_of(self, runtime: Any) -> Optional[str]:
        host = getattr(runtime, "host", None) if runtime else None
        parent = getattr(host, "parent", None) if host else None
        # A host's parent is typically a ClusterComputeResource (has a .name)
        return getattr(parent, "name", None) if parent else None

    def _datacenter_of(self, vm: Any) -> Optional[str]:
        # Walk up the parent chain until we hit a Datacenter.
        node = getattr(vm, "parent", None)
        seen = 0
        while node is not None and seen < 20:
            if type(node).__name__ == "vim.Datacenter" or "Datacenter" in type(node).__name__:
                return getattr(node, "name", None)
            node = getattr(node, "parent", None)
            seen += 1
        return None

    def _folder_path(self, vm: Any) -> Optional[str]:
        parts: list[str] = []
        node = getattr(vm, "parent", None)
        seen = 0
        while node is not None and seen < 20:
            tn = type(node).__name__
            if "Folder" in tn:
                nm = getattr(node, "name", None)
                if nm and nm != "vm":  # skip the implicit 'vm' root folder
                    parts.append(nm)
            node = getattr(node, "parent", None)
            seen += 1
        return "/".join(reversed(parts)) or None

    def _compute(self, config: Any) -> Compute:
        hw = getattr(config, "hardware", None)
        if hw is None:
            return Compute()
        num_cpu = getattr(hw, "numCPU", None)
        cps = getattr(hw, "numCoresPerSocket", None) or None
        sockets = (num_cpu // cps) if (num_cpu and cps) else None
        firmware = getattr(config, "firmware", None)  # 'bios' | 'efi'
        return Compute(
            vcpus=num_cpu,
            cores_per_socket=cps,
            sockets=sockets,
            memory_mb=getattr(hw, "memoryMB", None),
            architecture="x86_64",  # vSphere VMs are x86_64
            firmware=firmware,
        )

    def _devices(self, config: Any, guest: Any, vim: Any) -> tuple[list[Disk], list[Nic]]:
        disks: list[Disk] = []
        nics: list[Nic] = []
        hw = getattr(config, "hardware", None)
        devices = getattr(hw, "device", []) if hw else []

        # Pre-collect guest-reported IPs keyed by MAC (most reliable IP source).
        ips_by_mac = self._guest_ips_by_mac(guest)

        for dev in devices:
            if isinstance(dev, vim.vm.device.VirtualDisk):
                disks.append(self._disk(dev))
            elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
                nics.append(self._nic(dev, ips_by_mac))
        return disks, nics

    def _disk(self, dev: Any) -> Disk:
        cap_kb = getattr(dev, "capacityInKB", None)
        size_gb = round(cap_kb / (1024 * 1024), 2) if cap_kb else None
        backing = getattr(dev, "backing", None)
        file_name = getattr(backing, "fileName", None)
        thin = getattr(backing, "thinProvisioned", None)
        ds = self._name_of(getattr(backing, "datastore", None))
        provisioning = None
        if thin is True:
            provisioning = "thin"
        elif thin is False:
            provisioning = "thick"
        return Disk(
            label=getattr(getattr(dev, "deviceInfo", None), "label", None),
            size_gb=size_gb,
            backing=ds,
            path=file_name,
            provisioning=provisioning,
        )

    def _nic(self, dev: Any, ips_by_mac: dict[str, list[str]]) -> Nic:
        mac = getattr(dev, "macAddress", None)
        backing = getattr(dev, "backing", None)
        # Standard port group exposes deviceName; dvPortgroup needs a lookup we keep light.
        network = getattr(backing, "deviceName", None)
        if network is None:
            port = getattr(backing, "port", None)
            network = getattr(port, "portgroupKey", None)
        connectable = getattr(dev, "connectable", None)
        return Nic(
            label=getattr(getattr(dev, "deviceInfo", None), "label", None),
            mac=mac,
            ips=ips_by_mac.get(mac.lower(), []) if mac else [],
            network=network,
            connected=getattr(connectable, "connected", None),
        )

    def _guest_ips_by_mac(self, guest: Any) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if guest is None:
            return out
        for gnic in getattr(guest, "net", []) or []:
            mac = getattr(gnic, "macAddress", None)
            if not mac:
                continue
            ips = [ip for ip in (getattr(gnic, "ipAddress", []) or [])]
            out[mac.lower()] = ips
        return out

    def _os(self, config: Any, guest: Any) -> OSInfo:
        guest_full = (
            getattr(guest, "guestFullName", None)
            or getattr(config, "guestFullName", None)
        )
        family_raw = getattr(guest, "guestFamily", None) or getattr(config, "guestId", "")
        family = OSFamily.UNKNOWN
        for key, val in _GUEST_FAMILY_MAP.items():
            if family_raw and key.replace("Guest", "").lower() in str(family_raw).lower():
                family = val
                break
        if family is OSFamily.UNKNOWN and guest_full:
            low = guest_full.lower()
            if "windows" in low:
                family = OSFamily.WINDOWS
            elif any(x in low for x in ("linux", "ubuntu", "centos", "debian", "rhel", "suse")):
                family = OSFamily.LINUX
        return OSInfo(
            family=family,
            distro=guest_full,
            hostname=getattr(guest, "hostName", None),
        )

    def _tags(self, vm: Any) -> dict[str, str]:
        # vSphere tags live in the (separate) tagging service; custom fields are simpler and
        # available on the object. We surface custom field values here; vSphere tags are a
        # later enhancement.
        out: dict[str, str] = {}
        for cfv in getattr(vm, "customValue", []) or []:
            key = getattr(cfv, "key", None)
            val = getattr(cfv, "value", None)
            if key is not None and val:
                out[f"customfield:{key}"] = str(val)
        return out

    def _raw(self, config: Any, runtime: Any, summary: Any, is_template: bool) -> dict:
        raw: dict[str, Any] = {"is_template": is_template}
        if config is not None:
            raw["guestId"] = getattr(config, "guestId", None)
            raw["version"] = getattr(config, "version", None)  # vmx hardware version
            raw["uuid"] = getattr(config, "uuid", None)
            raw["instanceUuid"] = getattr(config, "instanceUuid", None)
        if runtime is not None:
            raw["bootTime"] = str(getattr(runtime, "bootTime", None))
            raw["connectionState"] = str(getattr(runtime, "connectionState", None))
        if summary is not None:
            qs = getattr(summary, "quickStats", None)
            if qs is not None:
                raw["uptimeSeconds"] = getattr(qs, "uptimeSeconds", None)
        return {k: v for k, v in raw.items() if v is not None}
