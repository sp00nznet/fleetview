"""The root of the unified data model: Provider, Node, and the Fleet snapshot.

A `Fleet` is one immutable, timestamped snapshot of one environment. Collectors produce it;
store/reproduce/analyze/frontend consume it. This is the contract the whole system pivots on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from .analysis import NodeAnalysis
from .enums import NodeKind, PowerState, ProviderKind
from .flows import DataFlow
from .inventory import Compute, Disk, Nic, OSInfo, Placement, SourceRef
from .software import SoftwareInventory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provider(BaseModel):
    """A connection FleetView collected from."""

    kind: ProviderKind
    instance: str = Field(..., description="stable id of this connection, e.g. vcenter hostname")
    display_name: Optional[str] = None
    endpoint: Optional[str] = Field(None, description="URL/host used to connect")
    collected_at: datetime = Field(default_factory=_utcnow)
    node_count: int = 0
    extra: dict = Field(default_factory=dict, description="provider-level facts (version, etc.)")


class Node(BaseModel):
    """A single box: VM, container, instance, or physical host. Provider-agnostic."""

    # --- identity ---
    id: str = Field(..., description="FleetView-stable id, '<provider>:<instance>:<native_id>'")
    name: str
    kind: NodeKind = NodeKind.UNKNOWN
    power_state: PowerState = PowerState.UNKNOWN

    # --- structure ---
    placement: Placement = Field(default_factory=Placement)
    compute: Compute = Field(default_factory=Compute)
    disks: list[Disk] = Field(default_factory=list)
    nics: list[Nic] = Field(default_factory=list)
    os: OSInfo = Field(default_factory=OSInfo)

    # --- runtime ---
    software: SoftwareInventory = Field(default_factory=SoftwareInventory)
    flows: list[DataFlow] = Field(default_factory=list)

    # --- metadata ---
    tags: dict[str, str] = Field(default_factory=dict)
    annotations: Optional[str] = Field(None, description="free-text notes from the provider")

    # --- provenance & derived ---
    source: SourceRef
    analysis: Optional[NodeAnalysis] = None

    @property
    def primary_ip(self) -> Optional[str]:
        for nic in self.nics:
            if nic.ips:
                return nic.ips[0]
        return None


class FleetMeta(BaseModel):
    id: str = Field(..., description="snapshot id")
    captured_at: datetime = Field(default_factory=_utcnow)
    fleetview_version: str = "0.1.0"
    scope: Optional[str] = Field(None, description="human label for what was scanned")
    warnings: list[str] = Field(
        default_factory=list, description="non-fatal issues during collection"
    )


class Fleet(BaseModel):
    """A complete, point-in-time picture of an environment."""

    meta: FleetMeta
    providers: list[Provider] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)

    # ---- convenience accessors (used by CLI summary, analyzer, frontend export) ----

    def nodes_by_provider(self, kind: ProviderKind) -> list[Node]:
        return [n for n in self.nodes if n.source.provider == kind]

    def node_index(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    @property
    def total_vcpus(self) -> int:
        return sum(n.compute.vcpus or 0 for n in self.nodes)

    @property
    def total_memory_gb(self) -> float:
        return round(sum((n.compute.memory_mb or 0) for n in self.nodes) / 1024, 1)

    @property
    def total_storage_gb(self) -> float:
        return round(sum(d.size_gb or 0 for n in self.nodes for d in n.disks), 1)
