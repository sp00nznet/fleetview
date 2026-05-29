"""Generate a schema-accurate sample Fleet snapshot for frontend development & demos.

Run: python tools/make_sample.py  ->  writes frontend/public/sample-fleet.json
Produces a small multi-provider fleet with data flows and analysis attached, so the frontend
can be built against realistic data before live collectors are wired in.
"""
from __future__ import annotations

import json
from pathlib import Path

from fleetview.models import (
    AppFingerprint,
    Compute,
    ConfidenceLevel,
    ContainerInfo,
    CostEstimate,
    DataFlow,
    Disk,
    DiskType,
    Endpoint,
    Finding,
    FindingCategory,
    FindingSeverity,
    Fleet,
    FleetMeta,
    FlowMechanism,
    ListeningPort,
    Nic,
    Node,
    NodeAnalysis,
    NodeKind,
    OSFamily,
    OSInfo,
    Package,
    Placement,
    PowerState,
    Provider,
    ProviderKind,
    Service,
    SoftwareInventory,
    SourceRef,
)


def _web(idx: int, provider: ProviderKind, instance: str, host: str, ip: str) -> Node:
    nid = f"{provider.value}:{instance}:web{idx:02d}"
    return Node(
        id=nid,
        name=f"web{idx:02d}",
        kind=NodeKind.VM,
        power_state=PowerState.RUNNING,
        placement=Placement(provider=provider, host=host, cluster="prod-cluster", datacenter="dc1"),
        compute=Compute(vcpus=4, memory_mb=8192, architecture="x86_64", instance_type="t3.large"),
        disks=[Disk(label="root", size_gb=80, disk_type=DiskType.SSD, backing="datastore1")],
        nics=[Nic(label="eth0", mac=f"00:50:56:aa:00:{idx:02d}", ips=[ip], network="prod-vlan10")],
        os=OSInfo(family=OSFamily.LINUX, distro="Ubuntu 22.04", version="22.04", hostname=f"web{idx:02d}"),
        software=SoftwareInventory(
            packages=[Package(name="nginx", version="1.18.0", manager="apt"),
                      Package(name="php-fpm", version="8.1", manager="apt")],
            services=[Service(name="nginx", state="running"), Service(name="php8.1-fpm", state="running")],
            listeners=[ListeningPort(port=443, process="nginx"), ListeningPort(port=80, process="nginx")],
            fingerprints=[AppFingerprint(name="nginx", category="webserver", version="1.18.0",
                                         confidence=ConfidenceLevel.OBSERVED, evidence=["port 443", "nginx.service"])],
            deep_inspected=True,
        ),
        flows=[
            DataFlow(mechanism=FlowMechanism.DB_CONNECTION, direction="outbound",
                     peer=Endpoint(node_id=f"{provider.value}:{instance}:db01", port=5432, label="db01:postgres"),
                     detail="app -> postgres", confidence=ConfidenceLevel.OBSERVED),
            DataFlow(mechanism=FlowMechanism.NFS_MOUNT, direction="inbound",
                     peer=Endpoint(address="10.0.0.50", label="nas01:/exports/assets"),
                     detail="/exports/assets -> /mnt/assets", confidence=ConfidenceLevel.OBSERVED),
        ],
        tags={"env": "prod", "role": "web"},
        source=SourceRef(provider=provider, provider_instance=instance, native_id=f"web{idx:02d}"),
        analysis=NodeAnalysis(
            findings=[Finding(id="rightsizing-cpu", category=FindingCategory.RIGHTSIZING,
                              severity=FindingSeverity.MEDIUM, title="Over-provisioned CPU",
                              detail="Peak vCPU utilization low for a 4-vCPU shape.",
                              recommendation="Downsize to 2 vCPU (t3.medium).",
                              estimated_monthly_savings_usd=30.0)],
            cost_estimates=[
                CostEstimate(platform=provider, instance_type="t3.large", monthly_usd=60.0,
                             basis="on-demand list", is_current=True),
                CostEstimate(platform=ProviderKind.GCP, instance_type="e2-standard-4", monthly_usd=52.0,
                             basis="on-demand list"),
                CostEstimate(platform=ProviderKind.PROXMOX, instance_type="4vcpu/8gb", monthly_usd=18.0,
                             basis="amortized hardware"),
            ],
        ),
    )


def _db(provider: ProviderKind, instance: str, host: str) -> Node:
    nid = f"{provider.value}:{instance}:db01"
    return Node(
        id=nid, name="db01", kind=NodeKind.VM, power_state=PowerState.RUNNING,
        placement=Placement(provider=provider, host=host, cluster="prod-cluster", datacenter="dc1"),
        compute=Compute(vcpus=8, memory_mb=32768, architecture="x86_64", instance_type="r6i.xlarge"),
        disks=[Disk(label="root", size_gb=100, disk_type=DiskType.SSD, backing="datastore1"),
               Disk(label="data", size_gb=500, disk_type=DiskType.NVME, backing="fast-pool")],
        nics=[Nic(label="eth0", mac="00:50:56:aa:00:99", ips=["10.0.0.20"], network="prod-vlan10")],
        os=OSInfo(family=OSFamily.LINUX, distro="Rocky Linux 8", version="8", hostname="db01", end_of_life=False),
        software=SoftwareInventory(
            packages=[Package(name="postgresql", version="14.5", manager="yum")],
            services=[Service(name="postgresql-14", state="running")],
            listeners=[ListeningPort(port=5432, process="postgres")],
            containers=[ContainerInfo(name="pgbackup", image="prodrigestivill/postgres-backup-local",
                                      runtime="docker", state="running")],
            fingerprints=[AppFingerprint(name="postgresql", category="database", version="14.5",
                                         confidence=ConfidenceLevel.OBSERVED, evidence=["port 5432"])],
            deep_inspected=True,
        ),
        flows=[DataFlow(mechanism=FlowMechanism.S3_SYNC, direction="outbound",
                        peer=Endpoint(address="s3://prod-db-backups", label="s3 backups"),
                        detail="nightly pg_dump -> s3", schedule="0 2 * * *",
                        confidence=ConfidenceLevel.OBSERVED)],
        tags={"env": "prod", "role": "db"},
        source=SourceRef(provider=provider, provider_instance=instance, native_id="db01"),
        analysis=NodeAnalysis(
            findings=[Finding(id="cost-platform", category=FindingCategory.COST,
                              severity=FindingSeverity.HIGH, title="Cheaper on-prem",
                              detail="This DB is a steady-state workload; cloud on-demand is costly.",
                              recommendation="Repatriate to Proxmox or buy reserved instance.",
                              estimated_monthly_savings_usd=210.0)],
            cost_estimates=[
                CostEstimate(platform=provider, instance_type="r6i.xlarge", monthly_usd=300.0,
                             basis="on-demand list", is_current=True),
                CostEstimate(platform=ProviderKind.PROXMOX, instance_type="8vcpu/32gb", monthly_usd=90.0,
                             basis="amortized hardware"),
            ],
        ),
    )


def build() -> Fleet:
    nodes = [
        _web(1, ProviderKind.AWS, "123456789012", "i-host-a", "10.0.0.11"),
        _web(2, ProviderKind.AWS, "123456789012", "i-host-b", "10.0.0.12"),
        _db(ProviderKind.AWS, "123456789012", "i-host-c"),
    ]
    providers = [Provider(kind=ProviderKind.AWS, instance="123456789012",
                          display_name="prod-account", node_count=len(nodes),
                          extra={"region": "us-east-1"})]
    return Fleet(
        meta=FleetMeta(id="sample-fleet", scope="demo: prod web tier + db (AWS)",
                       warnings=["sample data — not a real scan"]),
        providers=providers, nodes=nodes,
    )


def main() -> None:
    fleet = build()
    out = Path("frontend/public/sample-fleet.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fleet.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(fleet.nodes)} nodes)")


if __name__ == "__main__":
    main()
