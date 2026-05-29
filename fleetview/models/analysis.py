"""Analysis outputs: findings (improvements) and cross-platform cost estimates.

These are attached to a Node by the `analyze` engine (milestone 3). Defined now so the model,
schema, and frontend are stable before the engine exists.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import FindingCategory, FindingSeverity, ProviderKind


class Finding(BaseModel):
    """A single actionable observation about a node (or the fleet)."""

    id: str = Field(..., description="stable id, e.g. 'rightsizing-overprovisioned-cpu'")
    category: FindingCategory = FindingCategory.UNKNOWN
    severity: FindingSeverity = FindingSeverity.INFO
    title: str
    detail: Optional[str] = None
    recommendation: Optional[str] = Field(None, description="what to do about it")
    estimated_monthly_savings_usd: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)


class CostEstimate(BaseModel):
    """Estimated run cost of a node on a given platform.

    The point of FleetView's cost analysis is *comparison*: we compute the node's cost on its
    current platform and on alternatives, so the analyzer can say 'this is 40% cheaper as a
    Proxmox VM' or 'right-size to t3.medium and save $X'.
    """

    platform: ProviderKind
    instance_type: Optional[str] = Field(None, description="mapped shape on this platform")
    monthly_usd: Optional[float] = None
    basis: Optional[str] = Field(
        None, description="how it was computed (on-demand list price / amortized hw / ...)"
    )
    assumptions: list[str] = Field(default_factory=list)
    is_current: bool = Field(False, description="True if this is the node's current platform")


class NodeAnalysis(BaseModel):
    """Analysis bundle attached to a node after an analyze pass."""

    findings: list[Finding] = Field(default_factory=list)
    cost_estimates: list[CostEstimate] = Field(default_factory=list)

    @property
    def cheapest(self) -> Optional[CostEstimate]:
        priced = [c for c in self.cost_estimates if c.monthly_usd is not None]
        return min(priced, key=lambda c: c.monthly_usd) if priced else None
