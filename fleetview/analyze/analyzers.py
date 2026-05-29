"""Concrete analyzers. Each implements the `Analyzer` ABC and returns a `NodeAnalysis`.

No live metrics are used (by design) — findings are derived from *structure*: shape, OS,
software, tags, and the data-flow graph. Findings are worded conservatively where inferred.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ..models import (
    CostEstimate,
    Finding,
    FindingCategory,
    FindingSeverity,
    Fleet,
    Node,
    NodeAnalysis,
    PowerState,
    ProviderKind,
)
from . import Analyzer
from .pricing import estimate

# ---------------------------------------------------------------- cost


class CrossPlatformCostAnalyzer(Analyzer):
    """Price each node on its current platform AND alternatives — the cost-efficiency core."""

    name = "cross-platform-cost"

    #: platforms we always produce a comparison for
    TARGETS = (ProviderKind.AWS, ProviderKind.GCP, ProviderKind.PROXMOX)

    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        vcpus = node.compute.vcpus or 1
        mem = node.compute.memory_mb or 1024
        storage = sum(d.size_gb or 0 for d in node.disks)
        current = node.source.provider

        platforms = list(dict.fromkeys([current, *self.TARGETS]))  # de-dup, keep current first
        estimates: list[CostEstimate] = []
        for p in platforms:
            inst, monthly, assumptions = estimate(p, vcpus, mem, storage)
            if monthly is None:
                continue
            estimates.append(
                CostEstimate(
                    platform=p,
                    instance_type=inst,
                    monthly_usd=monthly,
                    basis=assumptions[0] if assumptions else None,
                    assumptions=assumptions,
                    is_current=(p == current),
                )
            )

        findings: list[Finding] = []
        priced = [e for e in estimates if e.monthly_usd is not None]
        cur = next((e for e in priced if e.is_current), None)
        cheapest = min(priced, key=lambda e: e.monthly_usd) if priced else None
        if cur and cheapest and cheapest.platform != cur.platform:
            savings = round(cur.monthly_usd - cheapest.monthly_usd, 2)
            if savings > 5:
                findings.append(
                    Finding(
                        id="cost-cheaper-platform",
                        category=FindingCategory.COST,
                        severity=FindingSeverity.MEDIUM if savings < 100 else FindingSeverity.HIGH,
                        title=f"Cheaper on {cheapest.platform.value}",
                        detail=(
                            f"Running at ~${cur.monthly_usd}/mo on {cur.platform.value}; "
                            f"~${cheapest.monthly_usd}/mo on {cheapest.platform.value} "
                            f"({cheapest.instance_type})."
                        ),
                        recommendation=(
                            f"Evaluate moving to {cheapest.platform.value}. "
                            "Verify data-gravity/egress and compliance before migrating."
                        ),
                        estimated_monthly_savings_usd=savings,
                    )
                )
        return NodeAnalysis(findings=findings, cost_estimates=estimates)


# ---------------------------------------------------------------- rightsizing


class RightsizingAnalyzer(Analyzer):
    """Structural rightsizing heuristics (no live metrics, so conservative)."""

    name = "rightsizing"
    LARGE_VCPU = 16
    LARGE_RAM_GB = 64

    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        findings: list[Finding] = []
        vcpus = node.compute.vcpus or 0
        ram_gb = (node.compute.memory_mb or 0) / 1024

        if node.power_state == PowerState.STOPPED:
            findings.append(
                Finding(
                    id="rightsizing-stopped-retained",
                    category=FindingCategory.HYGIENE,
                    severity=FindingSeverity.LOW,
                    title="Powered-off node still provisioned",
                    detail="Node is stopped but still consuming allocated storage/licensing.",
                    recommendation="Decommission or snapshot+delete if no longer needed.",
                )
            )
        if vcpus >= self.LARGE_VCPU or ram_gb >= self.LARGE_RAM_GB:
            findings.append(
                Finding(
                    id="rightsizing-large-shape",
                    category=FindingCategory.RIGHTSIZING,
                    severity=FindingSeverity.INFO,
                    title="Large instance — verify utilization",
                    detail=f"{vcpus} vCPU / {ram_gb:.0f} GB. No metrics captured; confirm it's needed.",
                    recommendation="Validate against actual load; downsize if over-provisioned.",
                )
            )
        # Lots of RAM but no recognizable memory-heavy app fingerprint
        roles = {fp.category for fp in node.software.fingerprints if fp.category}
        if ram_gb >= 32 and not ({"database", "cache", "queue"} & roles) and node.software.deep_inspected:
            findings.append(
                Finding(
                    id="rightsizing-ram-no-memapp",
                    category=FindingCategory.RIGHTSIZING,
                    severity=FindingSeverity.LOW,
                    title="High RAM without a memory-heavy workload",
                    detail=f"{ram_gb:.0f} GB RAM but no database/cache/queue detected.",
                    recommendation="Consider reducing memory allocation.",
                )
            )
        return NodeAnalysis(findings=findings)


# ---------------------------------------------------------------- end of life


class EOLAnalyzer(Analyzer):
    """Flag end-of-life / soon-EOL operating systems from a static table."""

    name = "eol"
    # substring(lower) -> human EOL note
    EOL = {
        "centos 6": "CentOS 6 — EOL Nov 2020",
        "centos 7": "CentOS 7 — EOL Jun 2024",
        "centos 8": "CentOS 8 — EOL Dec 2021",
        "ubuntu 14.04": "Ubuntu 14.04 — EOL 2019",
        "ubuntu 16.04": "Ubuntu 16.04 — EOL 2021",
        "ubuntu 18.04": "Ubuntu 18.04 — standard support ended 2023",
        "debian 8": "Debian 8 — EOL 2020",
        "debian 9": "Debian 9 — EOL 2022",
        "windows server 2008": "Windows Server 2008 — EOL Jan 2020",
        "windows server 2012": "Windows Server 2012 — EOL Oct 2023",
    }

    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        findings: list[Finding] = []
        hay = " ".join(filter(None, [node.os.distro, node.os.version])).lower()
        for needle, note in self.EOL.items():
            if needle in hay:
                findings.append(
                    Finding(
                        id="eol-os",
                        category=FindingCategory.MODERNIZATION,
                        severity=FindingSeverity.HIGH,
                        title="End-of-life operating system",
                        detail=note,
                        recommendation="Plan an OS upgrade/migration; unsupported = no security patches.",
                    )
                )
                break
        if node.os.end_of_life and not findings:
            findings.append(
                Finding(
                    id="eol-os",
                    category=FindingCategory.MODERNIZATION,
                    severity=FindingSeverity.HIGH,
                    title="End-of-life operating system",
                    detail=f"{node.os.distro or node.os.family.value} flagged EOL by collector.",
                    recommendation="Plan an OS upgrade/migration.",
                )
            )
        return NodeAnalysis(findings=findings)


# ---------------------------------------------------------------- hygiene


class HygieneAnalyzer(Analyzer):
    """Inventory hygiene: tags, orphaned/oversized disks, untracked configs."""

    name = "hygiene"

    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        findings: list[Finding] = []
        if not node.tags:
            findings.append(
                Finding(
                    id="hygiene-no-tags",
                    category=FindingCategory.HYGIENE,
                    severity=FindingSeverity.LOW,
                    title="Untagged node",
                    detail="No tags/labels — hard to attribute ownership or cost.",
                    recommendation="Add env/owner/role tags.",
                )
            )
        big = [d for d in node.disks if (d.size_gb or 0) >= 1000]
        if big:
            findings.append(
                Finding(
                    id="hygiene-large-disk",
                    category=FindingCategory.HYGIENE,
                    severity=FindingSeverity.INFO,
                    title="Large disk(s) attached",
                    detail=", ".join(f"{d.label or '?'}={d.size_gb:.0f}GB" for d in big),
                    recommendation="Confirm utilization; consider tiering cold data to object storage.",
                )
            )
        return NodeAnalysis(findings=findings)


# ---------------------------------------------------------------- fleet graph


class FleetGraphAnalyzer(Analyzer):
    """Graph-aware findings over the fleet's DataFlow edges.

    Ported in spirit from opsview's mount-topology analysis (redundant / circular /
    single-client), but generalized to any DataFlow mechanism. Computes fleet-wide structure
    once (cached on the fleet) and attaches the relevant findings to each node.
    """

    name = "fleet-graph"
    _CACHE_ATTR = "_fleetgraph_cache"

    def _peer_key(self, flow) -> str:
        p = flow.peer
        base = p.node_id or p.address or p.label or "?"
        return f"{flow.mechanism.value}:{base}"

    def _build(self, fleet: Fleet) -> dict:
        # consumers of each external/peer resource (for redundancy / single-client)
        consumers: dict[str, set[str]] = defaultdict(set)
        # directed edges between known nodes (for cycle detection)
        edges: dict[str, set[str]] = defaultdict(set)
        index = fleet.node_index()
        for node in fleet.nodes:
            for flow in node.flows:
                consumers[self._peer_key(flow)].add(node.id)
                if flow.peer.node_id and flow.peer.node_id in index:
                    if flow.direction == "inbound":
                        edges[flow.peer.node_id].add(node.id)
                    else:  # outbound / bidirectional
                        edges[node.id].add(flow.peer.node_id)
        cycles = self._find_cycles(edges)
        nodes_in_cycle = {n for cyc in cycles for n in cyc}
        return {"consumers": consumers, "cycles": cycles, "nodes_in_cycle": nodes_in_cycle}

    @staticmethod
    def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
        cycles: list[list[str]] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = defaultdict(int)
        stack: list[str] = []

        def dfs(u: str) -> None:
            color[u] = GRAY
            stack.append(u)
            for v in edges.get(u, ()):  # type: ignore[arg-type]
                if color[v] == GRAY:
                    if v in stack:
                        cycles.append(stack[stack.index(v):] + [v])
                elif color[v] == WHITE:
                    dfs(v)
            stack.pop()
            color[u] = BLACK

        for n in list(edges):
            if color[n] == WHITE:
                dfs(n)
        return cycles

    def analyze(self, node: Node, fleet: Fleet) -> NodeAnalysis:
        cache = getattr(fleet, self._CACHE_ATTR, None)
        if cache is None:
            cache = self._build(fleet)
            try:
                object.__setattr__(fleet, self._CACHE_ATTR, cache)
            except Exception:
                pass

        findings: list[Finding] = []
        # redundant: a peer this node uses that >=3 nodes also use -> consolidation candidate
        for flow in node.flows:
            key = self._peer_key(flow)
            users = cache["consumers"].get(key, set())
            if len(users) >= 3:
                peer_label = flow.peer.label or flow.peer.address or flow.peer.node_id or "?"
                findings.append(
                    Finding(
                        id="graph-shared-dependency",
                        category=FindingCategory.RELIABILITY,
                        severity=FindingSeverity.MEDIUM,
                        title="Widely-shared dependency (SPOF risk)",
                        detail=f"{len(users)} nodes depend on {peer_label} via {flow.mechanism.value}.",
                        recommendation="Ensure this dependency is HA; it's a single point of failure.",
                    )
                )
                break
        # circular dependency
        if node.id in cache["nodes_in_cycle"]:
            findings.append(
                Finding(
                    id="graph-circular-dependency",
                    category=FindingCategory.RELIABILITY,
                    severity=FindingSeverity.HIGH,
                    title="Circular dependency",
                    detail="This node participates in a circular data/dependency loop.",
                    recommendation="Break the cycle to avoid cascading failures and ordering deadlocks.",
                )
            )
        return NodeAnalysis(findings=findings)


def build_default_analyzers() -> list[Analyzer]:
    return [
        CrossPlatformCostAnalyzer(),
        RightsizingAnalyzer(),
        EOLAnalyzer(),
        HygieneAnalyzer(),
        FleetGraphAnalyzer(),
    ]
