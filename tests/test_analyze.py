from __future__ import annotations

from pathlib import Path

from fleetview.analyze import (
    EOLAnalyzer,
    analyze_fleet,
    build_default_analyzers,
    total_estimated_savings,
)
from fleetview.analyze.pricing import estimate
from fleetview.models import (
    Compute,
    DataFlow,
    Disk,
    Endpoint,
    Finding,
    Fleet,
    FleetMeta,
    FlowMechanism,
    Node,
    NodeKind,
    OSFamily,
    OSInfo,
    Provider,
    ProviderKind,
    SourceRef,
)


def _node(name, provider, vcpus=4, mem=8192, distro="Ubuntu 22.04", native=None):
    native = native or name
    return Node(
        id=f"{provider.value}:acct:{native}",
        name=name,
        kind=NodeKind.VM,
        compute=Compute(vcpus=vcpus, memory_mb=mem),
        disks=[Disk(label="root", size_gb=80)],
        os=OSInfo(family=OSFamily.LINUX, distro=distro),
        source=SourceRef(provider=provider, provider_instance="acct", native_id=native),
    )


def _fleet(nodes):
    return Fleet(meta=FleetMeta(id="t", scope="t"),
                 providers=[Provider(kind=ProviderKind.AWS, instance="acct")],
                 nodes=nodes)


def test_pricing_estimate_aws_and_onprem():
    inst, monthly, notes = estimate(ProviderKind.AWS, 4, 16384, 100)
    assert inst is not None and monthly and monthly > 0
    inst2, monthly2, _ = estimate(ProviderKind.PROXMOX, 4, 16384, 100)
    assert monthly2 and monthly2 > 0
    # on-prem amortized should be cheaper than AWS on-demand for steady-state
    assert monthly2 < monthly


def test_cost_analyzer_attaches_estimates_with_one_current():
    fleet = _fleet([_node("web01", ProviderKind.AWS)])
    analyze_fleet(fleet)
    node = fleet.nodes[0]
    assert node.analysis is not None
    estimates = node.analysis.cost_estimates
    assert len(estimates) >= 2
    assert sum(1 for e in estimates if e.is_current) == 1
    current = next(e for e in estimates if e.is_current)
    assert current.platform == ProviderKind.AWS


def test_eol_analyzer_flags_centos7():
    node = _node("legacy", ProviderKind.AWS, distro="CentOS 7")
    fleet = _fleet([node])
    result = EOLAnalyzer().analyze(node, fleet)
    assert any(f.id == "eol-os" for f in result.findings)


def test_total_savings_positive_for_expensive_aws_db():
    # big AWS box should be flagged cheaper on-prem -> savings > 0
    db = _node("db01", ProviderKind.AWS, vcpus=8, mem=32768)
    fleet = _fleet([db])
    analyze_fleet(fleet)
    assert total_estimated_savings(fleet) > 0


def test_fleet_graph_detects_shared_dependency():
    # three web nodes all mount the same NAS -> shared-dependency finding
    nas = Endpoint(address="10.0.0.50", label="nas01:/exports")
    nodes = []
    for i in range(3):
        n = _node(f"web{i}", ProviderKind.AWS, native=f"web{i}")
        n.flows = [DataFlow(mechanism=FlowMechanism.NFS_MOUNT, direction="inbound", peer=nas)]
        nodes.append(n)
    fleet = _fleet(nodes)
    analyze_fleet(fleet)
    assert any(
        f.id == "graph-shared-dependency"
        for n in fleet.nodes
        for f in (n.analysis.findings if n.analysis else [])
    )


def test_default_suite_runs_on_sample_fleet():
    sample = Path("frontend/public/sample-fleet.json")
    if not sample.exists():
        return  # sample optional in some checkouts
    fleet = Fleet.model_validate_json(sample.read_text(encoding="utf-8"))
    # clear any pre-baked analysis, then re-run
    for n in fleet.nodes:
        n.analysis = None
    analyze_fleet(fleet)
    assert all(n.analysis and n.analysis.cost_estimates for n in fleet.nodes)
    assert len(build_default_analyzers()) == 5
