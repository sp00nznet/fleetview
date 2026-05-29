"""GCP collector — Compute Engine instances in one project, via google-cloud-compute (read-only).

Maps each instance onto the unified `Node` model: machine type (-> instance_type + a best-effort
vCPU/memory parse for the standard families), attached disks, network interfaces (internal +
external/NAT IPs), placement (zone + derived region), labels -> tags, and power state. By default
it uses the aggregated list across every zone; pass ``zones`` to restrict the scan.

The provider instance is the GCP project. ``google-cloud-compute`` is imported lazily so the
rest of FleetView works without it installed.
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

_POWER_MAP = {
    "RUNNING": PowerState.RUNNING,
    "TERMINATED": PowerState.STOPPED,
    "STOPPED": PowerState.STOPPED,
    "STOPPING": PowerState.STOPPED,
    "SUSPENDED": PowerState.SUSPENDED,
    "SUSPENDING": PowerState.SUSPENDED,
    "PROVISIONING": PowerState.UNKNOWN,
    "STAGING": PowerState.UNKNOWN,
    "REPAIRING": PowerState.UNKNOWN,
}

# vCPU/memory (MiB) for common predefined machine types, by family + size token.
# e2/n1/n2/n2d standard families: vCPUs = size token; memory varies per family.
_FAMILY_MEM_PER_VCPU_MB = {
    "e2-standard": 4096,
    "e2-highmem": 8192,
    "e2-highcpu": 1024,
    "n1-standard": 3840,
    "n1-highmem": 6656,
    "n1-highcpu": 900,
    "n2-standard": 4096,
    "n2-highmem": 8192,
    "n2-highcpu": 1024,
    "n2d-standard": 4096,
    "n2d-highmem": 8192,
    "n2d-highcpu": 1024,
}

_DISK_TYPE_MAP = {
    "pd-ssd": DiskType.SSD,
    "pd-standard": DiskType.HDD,
    "pd-balanced": DiskType.SSD,
    "pd-extreme": DiskType.SSD,
    "local-ssd": DiskType.NVME,
}


class GCPCollector(Collector):
    provider_kind = ProviderKind.GCP

    def __init__(self, project: str, zones: Optional[list[str]] = None) -> None:
        self.project = project
        self.zones = zones
        self._client: Any = None

    # ----------------------------------------------------------------- connection

    def _instances_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import compute_v1  # type: ignore
        except ImportError as exc:
            raise CollectorError(
                "google-cloud-compute is not installed. "
                "Install with: pip install 'fleetview[gcp]'"
            ) from exc
        try:
            self._client = compute_v1.InstancesClient()
        except Exception as exc:
            raise CollectorError(f"Failed to create GCP Compute client: {exc}") from exc
        return self._client

    def test_connection(self) -> bool:
        client = self._instances_client()
        try:
            # aggregated_list is paginated/lazy; pulling the first page validates auth+project.
            it = client.aggregated_list(project=self.project)
            for _ in it:
                break
        except Exception as exc:
            raise CollectorError(f"GCP connection/auth failed: {exc}") from exc
        return True

    # ----------------------------------------------------------------- collection

    def collect(self) -> CollectResult:
        client = self._instances_client()

        provider = Provider(
            kind=ProviderKind.GCP,
            instance=self.project,
            display_name=f"gcp:{self.project}",
            endpoint="https://compute.googleapis.com",
            extra={"project": self.project},
        )

        warnings: list[str] = []
        nodes: list[Node] = []

        try:
            instances = list(self._iter_instances(client, warnings))
        except CollectorError:
            raise
        except Exception as exc:
            raise CollectorError(f"GCP instances list failed: {exc}") from exc

        for inst in instances:
            try:
                nodes.append(self._instance_to_node(inst))
            except Exception as exc:  # never let one bad instance kill the scan
                name = getattr(inst, "name", "<unknown>")
                warnings.append(f"Failed to map GCP instance '{name}': {exc}")

        provider.node_count = len(nodes)
        return CollectResult(provider=provider, nodes=nodes, warnings=warnings)

    def _iter_instances(self, client: Any, warnings: list[str]):
        if self.zones:
            for zone in self.zones:
                try:
                    for inst in client.list(project=self.project, zone=zone):
                        yield inst
                except Exception as exc:
                    warnings.append(f"Failed to list instances in zone '{zone}': {exc}")
            return
        # Aggregated list across all zones: yields (scope, scoped_list) pairs.
        for _scope, scoped in client.aggregated_list(project=self.project):
            for inst in getattr(scoped, "instances", []) or []:
                yield inst

    # ----------------------------------------------------------------- mapping

    def _instance_to_node(self, inst: Any) -> Node:
        native_id = str(getattr(inst, "id", "") or getattr(inst, "name", ""))
        node_id = self.make_node_id(ProviderKind.GCP, self.project, native_id)
        name = getattr(inst, "name", native_id)

        status = str(getattr(inst, "status", "") or "")
        power = _POWER_MAP.get(status, PowerState.UNKNOWN)

        zone = _last_segment(getattr(inst, "zone", ""))
        region = _region_from_zone(zone)
        placement = Placement(
            provider=ProviderKind.GCP,
            zone=zone,
            region=region,
            folder=self.project,
        )

        compute = self._compute(inst)
        disks = self._disks(inst)
        nics = self._nics(inst)
        os_info = self._os(inst)

        labels = dict(getattr(inst, "labels", {}) or {})

        return Node(
            id=node_id,
            name=name,
            kind=NodeKind.VM,
            power_state=power,
            placement=placement,
            compute=compute,
            disks=disks,
            nics=nics,
            os=os_info,
            tags=labels,
            annotations=getattr(inst, "description", None) or None,
            source=SourceRef(
                provider=ProviderKind.GCP,
                provider_instance=self.project,
                native_id=native_id,
                native_type="compute#instance",
                raw=self._raw(inst),
            ),
        )

    def _compute(self, inst: Any) -> Compute:
        machine_type = _last_segment(getattr(inst, "machine_type", ""))
        vcpus, mem_mb = _parse_machine_type(machine_type)
        cpu_platform = getattr(inst, "cpu_platform", None) or None
        return Compute(
            vcpus=vcpus,
            memory_mb=mem_mb,
            cpu_model=cpu_platform,
            architecture="x86_64",
            instance_type=machine_type or None,
        )

    def _disks(self, inst: Any) -> list[Disk]:
        disks: list[Disk] = []
        for d in getattr(inst, "disks", []) or []:
            size_gb = getattr(d, "disk_size_gb", None)
            init = getattr(d, "initialize_params", None)
            dtype_raw = _last_segment(getattr(init, "disk_type", "")) if init else ""
            label = getattr(d, "device_name", None)
            source = getattr(d, "source", None) or (
                getattr(init, "disk_name", None) if init else None
            )
            # Disk encryption: GCP encrypts at rest by default.
            encrypted = True
            disks.append(
                Disk(
                    label=label,
                    size_gb=float(size_gb) if size_gb else None,
                    disk_type=_DISK_TYPE_MAP.get(dtype_raw, DiskType.NETWORK),
                    backing=dtype_raw or None,
                    path=source,
                    encrypted=encrypted,
                )
            )
        return disks

    def _nics(self, inst: Any) -> list[Nic]:
        nics: list[Nic] = []
        for ni in getattr(inst, "network_interfaces", []) or []:
            ips: list[str] = []
            internal = getattr(ni, "network_i_p", None) or getattr(ni, "network_ip", None)
            if internal:
                ips.append(internal)
            for ac in getattr(ni, "access_configs", []) or []:
                nat = getattr(ac, "nat_i_p", None) or getattr(ac, "nat_ip", None)
                if nat:
                    ips.append(nat)
            nics.append(
                Nic(
                    label=getattr(ni, "name", None),
                    ips=ips,
                    network=_last_segment(getattr(ni, "subnetwork", "")) or None,
                    switch=_last_segment(getattr(ni, "network", "")) or None,
                )
            )
        return nics

    def _os(self, inst: Any) -> OSInfo:
        distro = None
        family = OSFamily.UNKNOWN
        for d in getattr(inst, "disks", []) or []:
            if not getattr(d, "boot", False):
                continue
            init = getattr(d, "initialize_params", None)
            src_image = _last_segment(getattr(init, "source_image", "")) if init else ""
            licenses = getattr(init, "licenses", []) if init else []
            blob = (src_image + " " + " ".join(str(x) for x in (licenses or []))).lower()
            distro = src_image or None
            if "windows" in blob:
                family = OSFamily.WINDOWS
            elif any(x in blob for x in ("debian", "ubuntu", "centos", "rhel", "linux", "cos")):
                family = OSFamily.LINUX
            break
        return OSInfo(family=family, distro=distro)

    @staticmethod
    def _raw(inst: Any) -> dict:
        # Prefer the proto-plus -> dict conversion; fall back to a light attribute scrape.
        try:
            from google.cloud import compute_v1  # type: ignore

            return compute_v1.Instance.to_dict(inst)  # type: ignore[attr-defined]
        except Exception:
            pass
        out: dict[str, Any] = {}
        for attr in ("id", "name", "status", "zone", "machine_type", "cpu_platform"):
            val = getattr(inst, attr, None)
            if val is not None:
                out[attr] = str(val)
        return out


# --------------------------------------------------------------------- module helpers


def _last_segment(url: Any) -> str:
    """GCP returns many fields as full resource URLs; we want the trailing name."""
    s = str(url or "")
    return s.rsplit("/", 1)[-1] if s else ""


def _region_from_zone(zone: str) -> Optional[str]:
    """'us-central1-a' -> 'us-central1'."""
    if not zone:
        return None
    return zone.rsplit("-", 1)[0] if "-" in zone else zone


_CUSTOM_RE = re.compile(r"(?:^|-)custom-(\d+)-(\d+)")


def _parse_machine_type(mt: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort vCPU + memory(MiB) from a predefined/custom machine type name."""
    if not mt:
        return None, None
    # custom machine types: [family-]custom-<vcpus>-<memMB>
    m = _CUSTOM_RE.search(mt)
    if m:
        return int(m.group(1)), int(m.group(2))
    # predefined: <family>-<size> where size is the vCPU count for standard families.
    parts = mt.rsplit("-", 1)
    if len(parts) == 2:
        family, size = parts
        try:
            vcpus = int(size)
        except ValueError:
            return None, None
        per = _FAMILY_MEM_PER_VCPU_MB.get(family)
        mem_mb = per * vcpus if per else None
        return vcpus, mem_mb
    return None, None
