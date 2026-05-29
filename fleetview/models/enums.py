"""Controlled vocabularies for the unified data model.

Keeping these as string enums (a) keeps JSON snapshots human-readable and (b) exports cleanly
to JSON Schema -> TypeScript string-literal unions for the frontend.
"""
from __future__ import annotations

from enum import Enum


class ProviderKind(str, Enum):
    """The platform a node lives on."""

    VMWARE = "vmware"        # vCenter or standalone ESXi
    PROXMOX = "proxmox"
    AWS = "aws"
    GCP = "gcp"
    UNKNOWN = "unknown"


class NodeKind(str, Enum):
    """What sort of 'box' this is."""

    VM = "vm"
    CONTAINER = "container"          # LXC / Docker / OCI
    BAREMETAL = "baremetal"
    MANAGED = "managed"             # managed service instance (RDS, Cloud SQL, ...)
    UNKNOWN = "unknown"


class PowerState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class OSFamily(str, Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    BSD = "bsd"
    OTHER = "other"
    UNKNOWN = "unknown"


class DiskType(str, Enum):
    SSD = "ssd"
    HDD = "hdd"
    NVME = "nvme"
    NETWORK = "network"     # iSCSI / NFS-backed / EBS / persistent disk
    UNKNOWN = "unknown"


class FlowMechanism(str, Enum):
    """How data/dependency moves between nodes — 'what's shuttled about'."""

    NFS_MOUNT = "nfs_mount"
    SMB_SHARE = "smb_share"
    ISCSI = "iscsi"
    RSYNC = "rsync"
    SCP_CRON = "scp_cron"
    S3_SYNC = "s3_sync"
    TCP_DEPENDENCY = "tcp_dependency"   # observed/declared connection to another node:port
    DB_CONNECTION = "db_connection"
    MESSAGE_QUEUE = "message_queue"
    HTTP_API = "http_api"
    SHARED_VOLUME = "shared_volume"
    UNKNOWN = "unknown"


class FindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(str, Enum):
    RIGHTSIZING = "rightsizing"     # over/under-provisioned compute/memory/disk
    COST = "cost"                   # cheaper elsewhere / wrong platform
    SECURITY = "security"
    RELIABILITY = "reliability"
    MODERNIZATION = "modernization" # EOL OS, could be containerized, etc.
    HYGIENE = "hygiene"             # orphaned disks, stale snapshots, no tags
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    """How sure a collector/analyzer is about a derived value."""

    OBSERVED = "observed"       # read directly from the provider/guest
    INFERRED = "inferred"       # derived from other signals
    ASSUMED = "assumed"         # default/heuristic fallback
