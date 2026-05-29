"""AWS collector — EC2 instances (+ best-effort RDS) in one region, via boto3 (read-only).

Maps each EC2 instance onto the unified `Node` model: instance type (and its vCPU/memory shape,
looked up once per type and cached), EBS volumes as disks, ENIs as NICs (private/public IPs,
MAC, subnet, security groups), placement (region/AZ/host), Tags, and power state. RDS instances
are enumerated as NodeKind.MANAGED on a best-effort basis (wrapped in try/except).

The provider instance is the AWS account id (sts:GetCallerIdentity). boto3 is imported lazily so
the rest of FleetView works without it installed.
"""
from __future__ import annotations

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
    "running": PowerState.RUNNING,
    "stopped": PowerState.STOPPED,
    "stopping": PowerState.STOPPED,
    "shutting-down": PowerState.STOPPED,
    "terminated": PowerState.STOPPED,
    "pending": PowerState.UNKNOWN,
}

# EBS volume type -> unified DiskType
_VOLUME_TYPE_MAP = {
    "gp2": DiskType.SSD,
    "gp3": DiskType.SSD,
    "io1": DiskType.SSD,
    "io2": DiskType.SSD,
    "st1": DiskType.HDD,
    "sc1": DiskType.HDD,
    "standard": DiskType.HDD,
}


class AWSCollector(Collector):
    provider_kind = ProviderKind.AWS

    def __init__(
        self,
        region: str,
        profile: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        self.region = region
        self.profile = profile
        self.access_key = access_key
        self.secret_key = secret_key
        self._session: Any = None
        self._account_id: Optional[str] = None
        self._type_cache: dict[str, tuple[Optional[int], Optional[int]]] = {}

    # ----------------------------------------------------------------- connection

    def _sess(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise CollectorError(
                "boto3 is not installed. Install with: pip install 'fleetview[aws]'"
            ) from exc
        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.profile:
            kwargs["profile_name"] = self.profile
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        try:
            self._session = boto3.Session(**kwargs)
        except Exception as exc:
            raise CollectorError(f"Failed to create AWS session: {exc}") from exc
        return self._session

    def _client(self, service: str) -> Any:
        return self._sess().client(service)

    def _get_account_id(self) -> Optional[str]:
        if self._account_id is not None:
            return self._account_id
        try:
            ident = self._client("sts").get_caller_identity()
            self._account_id = ident.get("Account")
        except Exception:
            self._account_id = None
        return self._account_id

    def test_connection(self) -> bool:
        try:
            self._client("sts").get_caller_identity()
        except Exception as exc:
            raise CollectorError(f"AWS connection/auth failed: {exc}") from exc
        return True

    # ----------------------------------------------------------------- collection

    def collect(self) -> CollectResult:
        self._sess()
        account_id = self._get_account_id()
        instance_key = account_id or self.region

        provider = Provider(
            kind=ProviderKind.AWS,
            instance=instance_key,
            display_name=f"aws:{account_id or '?'}:{self.region}",
            endpoint=f"https://ec2.{self.region}.amazonaws.com",
            extra={"account_id": account_id, "region": self.region},
        )

        warnings: list[str] = []
        nodes: list[Node] = []

        ec2 = self._client("ec2")

        # Pre-fetch volume details so we can enrich block device mappings.
        volumes_by_id = self._volumes_by_id(ec2, warnings)

        try:
            paginator = ec2.get_paginator("describe_instances")
            pages = paginator.paginate()
        except Exception as exc:
            raise CollectorError(f"AWS describe_instances failed: {exc}") from exc

        for page in pages:
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    try:
                        nodes.append(
                            self._instance_to_node(inst, ec2, instance_key, volumes_by_id)
                        )
                    except Exception as exc:  # never let one bad instance kill the scan
                        iid = inst.get("InstanceId", "<unknown>")
                        warnings.append(f"Failed to map EC2 instance '{iid}': {exc}")

        # RDS — best effort.
        try:
            nodes.extend(self._rds_nodes(instance_key, warnings))
        except Exception as exc:
            warnings.append(f"Failed to enumerate RDS instances: {exc}")

        provider.node_count = len(nodes)
        return CollectResult(provider=provider, nodes=nodes, warnings=warnings)

    # ----------------------------------------------------------------- EC2 mapping

    def _instance_to_node(
        self,
        inst: dict,
        ec2: Any,
        instance_key: str,
        volumes_by_id: dict[str, dict],
    ) -> Node:
        iid = inst["InstanceId"]
        node_id = self.make_node_id(ProviderKind.AWS, instance_key, iid)

        tags = {t["Key"]: t.get("Value", "") for t in inst.get("Tags", []) or []}
        name = tags.get("Name") or iid

        state = (inst.get("State") or {}).get("Name", "")
        power = _POWER_MAP.get(state, PowerState.UNKNOWN)

        placement_raw = inst.get("Placement") or {}
        placement = Placement(
            provider=ProviderKind.AWS,
            region=self.region,
            zone=placement_raw.get("AvailabilityZone"),
            host=placement_raw.get("HostId") or placement_raw.get("GroupName") or None,
            datacenter=self.region,
        )

        compute = self._compute(inst, ec2)
        disks = self._disks(inst, volumes_by_id)
        nics = self._nics(inst)
        os_info = self._os(inst)

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
            tags=tags,
            source=SourceRef(
                provider=ProviderKind.AWS,
                provider_instance=instance_key,
                native_id=iid,
                native_type="ec2:instance",
                raw=_jsonable(inst),
            ),
        )

    def _compute(self, inst: dict, ec2: Any) -> Compute:
        itype = inst.get("InstanceType")
        vcpus, mem_mb = self._type_shape(itype, ec2)
        arch = inst.get("Architecture")  # 'x86_64' | 'arm64'
        return Compute(
            vcpus=vcpus,
            memory_mb=mem_mb,
            architecture=arch,
            firmware=inst.get("BootMode"),
            instance_type=itype,
        )

    def _type_shape(
        self, itype: Optional[str], ec2: Any
    ) -> tuple[Optional[int], Optional[int]]:
        """vCPUs + memory (MiB) for an instance type, cached per type."""
        if not itype:
            return None, None
        if itype in self._type_cache:
            return self._type_cache[itype]
        vcpus: Optional[int] = None
        mem_mb: Optional[int] = None
        try:
            resp = ec2.describe_instance_types(InstanceTypes=[itype])
            infos = resp.get("InstanceTypes", [])
            if infos:
                info = infos[0]
                vcpus = (info.get("VCpuInfo") or {}).get("DefaultVCpus")
                mem_mb = (info.get("MemoryInfo") or {}).get("SizeInMiB")
        except Exception:
            pass
        self._type_cache[itype] = (vcpus, mem_mb)
        return vcpus, mem_mb

    def _disks(self, inst: dict, volumes_by_id: dict[str, dict]) -> list[Disk]:
        disks: list[Disk] = []
        for bdm in inst.get("BlockDeviceMappings", []) or []:
            ebs = bdm.get("Ebs") or {}
            vol_id = ebs.get("VolumeId")
            vol = volumes_by_id.get(vol_id, {}) if vol_id else {}
            vol_type = vol.get("VolumeType")
            disks.append(
                Disk(
                    label=bdm.get("DeviceName"),
                    size_gb=vol.get("Size"),
                    disk_type=_VOLUME_TYPE_MAP.get(vol_type, DiskType.NETWORK),
                    backing="ebs",
                    path=vol_id,
                    encrypted=vol.get("Encrypted"),
                    iops=vol.get("Iops"),
                )
            )
        return disks

    def _nics(self, inst: dict) -> list[Nic]:
        nics: list[Nic] = []
        for eni in inst.get("NetworkInterfaces", []) or []:
            ips: list[str] = []
            for pa in eni.get("PrivateIpAddresses", []) or []:
                pip = pa.get("PrivateIpAddress")
                if pip:
                    ips.append(pip)
                assoc = pa.get("Association") or {}
                pub = assoc.get("PublicIp")
                if pub:
                    ips.append(pub)
            if not ips and eni.get("PrivateIpAddress"):
                ips.append(eni["PrivateIpAddress"])
            sgs = [g.get("GroupId") for g in eni.get("Groups", []) or [] if g.get("GroupId")]
            attachment = eni.get("Attachment") or {}
            nics.append(
                Nic(
                    label=eni.get("NetworkInterfaceId"),
                    mac=eni.get("MacAddress"),
                    ips=ips,
                    network=eni.get("SubnetId"),
                    switch=eni.get("VpcId"),
                    security_groups=sgs,
                    connected=attachment.get("Status") == "attached",
                )
            )
        # Fall back to top-level IPs if no ENIs were reported.
        if not nics:
            ips = []
            if inst.get("PrivateIpAddress"):
                ips.append(inst["PrivateIpAddress"])
            if inst.get("PublicIpAddress"):
                ips.append(inst["PublicIpAddress"])
            if ips:
                nics.append(Nic(label="primary", ips=ips))
        return nics

    def _os(self, inst: dict) -> OSInfo:
        platform = (inst.get("Platform") or "").lower()  # 'windows' or absent
        details = (inst.get("PlatformDetails") or "")
        family = OSFamily.UNKNOWN
        if platform == "windows" or "windows" in details.lower():
            family = OSFamily.WINDOWS
        elif "linux" in details.lower() or details:
            family = OSFamily.LINUX
        return OSInfo(family=family, distro=details or None)

    # ----------------------------------------------------------------- helpers

    def _volumes_by_id(self, ec2: Any, warnings: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        try:
            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for vol in page.get("Volumes", []):
                    vid = vol.get("VolumeId")
                    if vid:
                        out[vid] = vol
        except Exception as exc:
            warnings.append(f"Failed to describe EBS volumes: {exc}")
        return out

    # ----------------------------------------------------------------- RDS mapping

    def _rds_nodes(self, instance_key: str, warnings: list[str]) -> list[Node]:
        nodes: list[Node] = []
        rds = self._client("rds")
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                try:
                    nodes.append(self._db_to_node(db, instance_key))
                except Exception as exc:
                    dbid = db.get("DBInstanceIdentifier", "<unknown>")
                    warnings.append(f"Failed to map RDS instance '{dbid}': {exc}")
        return nodes

    def _db_to_node(self, db: dict, instance_key: str) -> Node:
        dbid = db.get("DBInstanceIdentifier")
        arn = db.get("DBInstanceArn") or dbid
        node_id = self.make_node_id(ProviderKind.AWS, instance_key, arn)

        status = (db.get("DBInstanceStatus") or "").lower()
        power = PowerState.RUNNING if status == "available" else PowerState.UNKNOWN
        if status in ("stopped",):
            power = PowerState.STOPPED

        az = db.get("AvailabilityZone")
        placement = Placement(
            provider=ProviderKind.AWS,
            region=self.region,
            zone=az,
            datacenter=self.region,
        )

        compute = Compute(instance_type=db.get("DBInstanceClass"))

        disks = []
        if db.get("AllocatedStorage"):
            disks.append(
                Disk(
                    label="storage",
                    size_gb=db.get("AllocatedStorage"),
                    disk_type=_VOLUME_TYPE_MAP.get(db.get("StorageType"), DiskType.NETWORK),
                    backing="rds",
                    encrypted=db.get("StorageEncrypted"),
                    iops=db.get("Iops"),
                )
            )

        nics = []
        endpoint = db.get("Endpoint") or {}
        if endpoint.get("Address"):
            nics.append(Nic(label="endpoint", ips=[endpoint["Address"]]))

        tags = {t["Key"]: t.get("Value", "") for t in db.get("TagList", []) or []}

        return Node(
            id=node_id,
            name=dbid or arn,
            kind=NodeKind.MANAGED,
            power_state=power,
            placement=placement,
            compute=compute,
            disks=disks,
            nics=nics,
            os=OSInfo(),
            tags=tags,
            annotations=db.get("Engine"),
            source=SourceRef(
                provider=ProviderKind.AWS,
                provider_instance=instance_key,
                native_id=str(arn),
                native_type="rds:db",
                raw=_jsonable(db),
            ),
        )


def _jsonable(obj: Any) -> Any:
    """Convert boto3 payloads (datetimes etc.) into JSON-serializable structures for raw."""
    import datetime as _dt

    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, _dt.datetime):
        return obj.isoformat()
    return obj
