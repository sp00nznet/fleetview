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


# NOTE: concrete analyzers (RightsizingAnalyzer, CrossPlatformCostAnalyzer, EOLAnalyzer, ...)
# land in M3, backed by a pricing data module.
