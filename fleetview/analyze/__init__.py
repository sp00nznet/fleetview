"""Analyze engine — findings (improvements) + cross-platform cost.

Milestone 3. Interface defined now so the model carries the right fields. An `Analyzer` reads
a Node (and optionally the whole Fleet for graph-aware checks) and attaches a `NodeAnalysis`:
rightsizing, modernization, hygiene findings, and a cost estimate on each platform so we can
say where the box runs cheapest.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Fleet, Node, NodeAnalysis


class Analyzer(ABC):
    """Produces a NodeAnalysis for a node, optionally using fleet-wide context."""

    name: str

    @abstractmethod
    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        ...


def run_analyzers(fleet: Fleet, analyzers: list[Analyzer]) -> Fleet:
    """Attach merged analysis from every analyzer to every node. Returns the same fleet."""
    for node in fleet.nodes:
        findings = []
        costs = []
        for az in analyzers:
            result = az.analyze(node, fleet)
            findings.extend(result.findings)
            costs.extend(result.cost_estimates)
        if findings or costs:
            node.analysis = NodeAnalysis(findings=findings, cost_estimates=costs)
    return fleet


def analyze_fleet(fleet: Fleet) -> Fleet:
    """Run the default analyzer suite over the fleet (convenience)."""
    return run_analyzers(fleet, build_default_analyzers())


def total_estimated_savings(fleet: Fleet) -> float:
    """Sum of estimated monthly savings across all findings in the fleet."""
    total = 0.0
    for node in fleet.nodes:
        if node.analysis:
            total += sum(f.estimated_monthly_savings_usd or 0 for f in node.analysis.findings)
    return round(total, 2)


# Imported at the bottom so analyzers.py can `from . import Analyzer` without a cycle.
from .analyzers import (  # noqa: E402
    CrossPlatformCostAnalyzer,
    EOLAnalyzer,
    FleetGraphAnalyzer,
    HygieneAnalyzer,
    RightsizingAnalyzer,
    build_default_analyzers,
)

__all__ = [
    "Analyzer",
    "run_analyzers",
    "analyze_fleet",
    "total_estimated_savings",
    "build_default_analyzers",
    "CrossPlatformCostAnalyzer",
    "RightsizingAnalyzer",
    "EOLAnalyzer",
    "HygieneAnalyzer",
    "FleetGraphAnalyzer",
]


# NOTE: concrete analyzers (RightsizingAnalyzer, CrossPlatformCostAnalyzer, EOLAnalyzer, ...)
# land in M3, backed by a pricing data module.
