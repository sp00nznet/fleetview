"""Unit tests for the GCP collector — google-cloud-compute is faked.

We inject a fake `google.cloud.compute_v1` module with an InstancesClient whose
aggregated_list returns canned instance objects, then assert the mapping into Node.
"""
from __future__ import annotations

import sys
import types

import pytest

from fleetview.collectors.base import CollectorError
from fleetview.collectors.gcp import GCPCollector
from fleetview.models import DiskType, NodeKind, OSFamily, PowerState, ProviderKind


# ---- fake compute_v1 object graph ---------------------------------------------

def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _make_instance():
    init = _ns(
        disk_type="https://www.googleapis.com/.../diskTypes/pd-ssd",
        source_image="https://www.googleapis.com/.../images/debian-12-bookworm",
        licenses=["https://.../debian-12"],
        disk_name="boot-disk",
    )
    boot_disk = _ns(boot=True, device_name="persistent-disk-0", disk_size_gb=50,
                    initialize_params=init, source="projects/p/disks/boot-disk")
    nic = _ns(
        name="nic0",
        network_i_p="10.128.0.2",
        access_configs=[_ns(nat_i_p="34.10.20.30")],
        subnetwork="https://.../subnetworks/default-sub",
        network="https://.../networks/default",
    )
    return _ns(
        id=123456789,
        name="vm-web-1",
        status="RUNNING",
        zone="https://www.googleapis.com/compute/v1/projects/p/zones/us-central1-a",
        machine_type="https://.../machineTypes/e2-standard-4",
        cpu_platform="Intel Broadwell",
        description="frontend node",
        labels={"env": "prod", "team": "web"},
        disks=[boot_disk],
        network_interfaces=[nic],
    )


class _ScopedList:
    def __init__(self, instances):
        self.instances = instances


class _FakeInstancesClient:
    def __init__(self):
        self._inst = _make_instance()

    def aggregated_list(self, project=None):
        # yields (scope, scoped_list) pairs
        return iter([
            ("zones/us-central1-a", _ScopedList([self._inst])),
            ("zones/us-east1-b", _ScopedList([])),
        ])

    def list(self, project=None, zone=None):
        return iter([self._inst]) if zone == "us-central1-a" else iter([])


@pytest.fixture
def fake_compute(monkeypatch):
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    compute_v1 = types.ModuleType("google.cloud.compute_v1")
    compute_v1.InstancesClient = _FakeInstancesClient

    class _Instance:
        @staticmethod
        def to_dict(inst):
            return {"id": str(inst.id), "name": inst.name, "status": inst.status}

    compute_v1.Instance = _Instance
    google.cloud = cloud
    cloud.compute_v1 = compute_v1

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.compute_v1", compute_v1)
    return compute_v1


def test_missing_sdk_raises_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.cloud.compute_v1", None)  # ImportError
    c = GCPCollector("my-project")
    with pytest.raises(CollectorError) as ei:
        c.test_connection()
    assert "pip install 'fleetview[gcp]'" in str(ei.value)


def test_collect_aggregated_maps_instance(fake_compute):
    c = GCPCollector("my-project")
    result = c.collect()

    assert result.provider.kind is ProviderKind.GCP
    assert result.provider.instance == "my-project"
    assert result.provider.node_count == 1

    n = result.nodes[0]
    assert n.name == "vm-web-1"
    assert n.kind is NodeKind.VM
    assert n.id == "gcp:my-project:123456789"
    assert n.power_state is PowerState.RUNNING
    # machine type parse: e2-standard-4 -> 4 vcpus, 4*4096 MiB
    assert n.compute.instance_type == "e2-standard-4"
    assert n.compute.vcpus == 4
    assert n.compute.memory_mb == 4 * 4096
    assert n.compute.cpu_model == "Intel Broadwell"
    # placement: zone + derived region
    assert n.placement.zone == "us-central1-a"
    assert n.placement.region == "us-central1"
    assert n.placement.folder == "my-project"
    # disk
    assert n.disks[0].size_gb == 50.0
    assert n.disks[0].disk_type is DiskType.SSD
    assert n.disks[0].encrypted is True
    # nic: internal + external IP
    assert n.nics[0].ips == ["10.128.0.2", "34.10.20.30"]
    assert n.primary_ip == "10.128.0.2"
    assert n.nics[0].network == "default-sub"
    assert n.nics[0].switch == "default"
    # labels -> tags
    assert n.tags == {"env": "prod", "team": "web"}
    assert n.annotations == "frontend node"
    # OS detection from boot image
    assert n.os.family is OSFamily.LINUX
    assert "debian" in (n.os.distro or "")
    # raw fidelity
    assert n.source.raw["name"] == "vm-web-1"
    assert n.source.native_type == "compute#instance"


def test_collect_with_explicit_zone(fake_compute):
    c = GCPCollector("my-project", zones=["us-central1-a"])
    result = c.collect()
    assert result.provider.node_count == 1
    assert result.nodes[0].placement.zone == "us-central1-a"


def test_bad_instance_becomes_warning(fake_compute, monkeypatch):
    c = GCPCollector("my-project")

    def boom(inst):
        raise RuntimeError("map fail")

    monkeypatch.setattr(c, "_instance_to_node", boom)
    result = c.collect()
    assert result.nodes == []
    assert any("map fail" in w for w in result.warnings)
