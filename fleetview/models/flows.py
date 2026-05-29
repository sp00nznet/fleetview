"""DataFlow: the edges of the fleet graph — "what files/data are being shuttled about".

A flow connects this node to another endpoint (another node, an external host, an object
store, a database). The fleet as a whole is a directed graph of nodes + flows, which the
frontend renders and the analyzer walks (e.g. "this DB has 12 inbound app dependencies").
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import ConfidenceLevel, FlowMechanism


class Endpoint(BaseModel):
    """One side of a flow. Prefer node_id when the other side is a known fleet node."""

    node_id: Optional[str] = Field(None, description="fleet Node.id if the peer is known")
    address: Optional[str] = Field(None, description="host/ip/url/bucket if peer is external/unknown")
    port: Optional[int] = None
    label: Optional[str] = Field(None, description="human label, e.g. 'nfs-server' / 's3://backups'")


class DataFlow(BaseModel):
    """A directional data/dependency relationship originating from the owning node."""

    mechanism: FlowMechanism = FlowMechanism.UNKNOWN
    direction: str = Field("outbound", description="outbound | inbound | bidirectional")
    peer: Endpoint
    detail: Optional[str] = Field(
        None, description="e.g. mount path, cron schedule, share name, query target"
    )
    schedule: Optional[str] = Field(None, description="cron expr / 'continuous' / 'on-demand'")
    confidence: ConfidenceLevel = ConfidenceLevel.INFERRED
    evidence: list[str] = Field(
        default_factory=list, description="how this flow was discovered (fstab line, cron entry, ...)"
    )
