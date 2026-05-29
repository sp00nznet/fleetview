"""The unified model is the contract — these tests pin its core behaviour."""
from __future__ import annotations

from fleetview.models import (
    Compute,
    DataFlow,
    Disk,
    Endpoint,
    Fleet,
    FleetMeta,
    FlowMechanism,
    Nic,
    Node,
    NodeKind,
    OSFamily,
    OSInfo,
    PowerState,
    Provider,
    ProviderKind,
    SourceRef,
)


def _sample_node(name: str = "web01", native: str = "vm-101") -> Node:
    return Node(
        id=f"vmware:vcenter.local:{native}",
        name=name,
        kind=NodeKind.VM,
        power_state=PowerState.RUNNING,
        compute=Compute(vcpus=4, memory_mb=8192),
        disks=[Disk(label="Hard disk 1", size_gb=80.0, backing="datastore1")],
        nics=[Nic(label="nic0", mac="00:50:56:aa:bb:cc", ips=["10.0.0.10"], network="VLAN10")],
        os=OSInfo(family=OSFamily.LINUX, distro="Ubuntu 22.04", hostname=name),
        flows=[
            DataFlow(
                mechanism=FlowMechanism.NFS_MOUNT,
                peer=Endpoint(address="10.0.0.5", label="nfs-server"),
                detail="/exports/data -> /mnt/data",
            )
        ],
        source=SourceRef(
            provider=ProviderKind.VMWARE, provider_instance="vcenter.local", native_id=native
        ),
    )


def _sample_fleet() -> Fleet:
    return Fleet(
        meta=FleetMeta(id="test-snap", scope="unit-test"),
        providers=[Provider(kind=ProviderKind.VMWARE, instance="vcenter.local", node_count=2)],
        nodes=[_sample_node("web01", "vm-101"), _sample_node("db01", "vm-102")],
    )


def test_node_id_helper():
    from fleetview.collectors.base import Collector

    assert (
        Collector.make_node_id(ProviderKind.VMWARE, "vcenter.local", "vm-101")
        == "vmware:vcenter.local:vm-101"
    )


def test_primary_ip():
    assert _sample_node().primary_ip == "10.0.0.10"


def test_fleet_rollups():
    fleet = _sample_fleet()
    assert fleet.total_vcpus == 8
    assert fleet.total_memory_gb == 16.0
    assert fleet.total_storage_gb == 160.0
    assert len(fleet.nodes_by_provider(ProviderKind.VMWARE)) == 2
    assert set(fleet.node_index()) == {
        "vmware:vcenter.local:vm-101",
        "vmware:vcenter.local:vm-102",
    }


def test_json_round_trip():
    fleet = _sample_fleet()
    blob = fleet.model_dump_json()
    restored = Fleet.model_validate_json(blob)
    assert restored == fleet
    # enums survive the round trip as enums
    assert restored.nodes[0].power_state is PowerState.RUNNING
    assert restored.nodes[0].flows[0].mechanism is FlowMechanism.NFS_MOUNT


def test_schema_export_is_valid_json_schema():
    from fleetview.schema import fleet_json_schema

    schema = fleet_json_schema()
    assert schema["title"] == "Fleet"
    assert "properties" in schema and "nodes" in schema["properties"]
