"""Unit tests for the Proxmox collector — the HTTP layer (requests) is faked.

We inject a fake `requests` module into sys.modules and a canned PVE REST API so the collector
runs end-to-end offline, then assert the mapping into the unified Node model.
"""
from __future__ import annotations

import sys
import types

import pytest

from fleetview.collectors.base import CollectorError
from fleetview.collectors.proxmox import ProxmoxCollector
from fleetview.models import DiskType, NodeKind, PowerState, ProviderKind

# ---- canned PVE REST responses ------------------------------------------------

_VERSION = {"version": "8.1.4", "release": "8.1"}
_NODES = [{"node": "pve1", "status": "online"}, {"node": "pve2", "status": "online"}]

_RESOURCES = [
    {"type": "qemu", "vmid": 100, "name": "web01", "node": "pve1", "status": "running",
     "pool": "prod", "maxcpu": 4, "maxmem": 8 * 1024 * 1024 * 1024},
    {"type": "lxc", "vmid": 200, "name": "ct-redis", "node": "pve2", "status": "running",
     "pool": "infra"},
    {"type": "storage", "vmid": 0, "name": "local", "node": "pve1"},  # ignored
]

_QEMU_CONFIG = {
    "cores": 2, "sockets": 2, "memory": 8192, "bios": "ovmf",
    "ostype": "l26", "name": "web01", "description": "frontend",
    "tags": "web;public",
    "scsi0": "local-lvm:vm-100-disk-0,size=32G,discard=on",
    "ide2": "local:iso/debian.iso,media=cdrom",
    "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10",
}

_LXC_CONFIG = {
    "cores": 1, "memory": 1024, "ostype": "debian", "hostname": "ct-redis",
    "rootfs": "local-lvm:subvol-200-disk-0,size=8G",
    "net0": "name=eth0,bridge=vmbr1,ip=10.0.0.50/24,hwaddr=12:34:56:78:9A:BC",
}

_AGENT_IFACES = {
    "result": [
        {"name": "lo", "ip-addresses": [
            {"ip-address-type": "ipv4", "ip-address": "127.0.0.1"}]},
        {"name": "eth0", "ip-addresses": [
            {"ip-address-type": "ipv4", "ip-address": "192.168.1.10"}]},
    ]
}


class _FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = str(data)

    def json(self):
        return {"data": self._data}


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.verify = True
        self.cookies = types.SimpleNamespace(set=lambda *a, **k: None)
        self.calls: list[str] = []

    def get(self, url, timeout=None, **kwargs):
        self.calls.append(url)
        if url.endswith("/version"):
            return _FakeResponse(_VERSION)
        if url.endswith("/nodes"):
            return _FakeResponse(_NODES)
        if url.endswith("/cluster/resources"):
            return _FakeResponse(_RESOURCES)
        if url.endswith("/nodes/pve1/qemu/100/config"):
            return _FakeResponse(_QEMU_CONFIG)
        if url.endswith("/nodes/pve2/lxc/200/config"):
            return _FakeResponse(_LXC_CONFIG)
        if "agent/network-get-interfaces" in url:
            return _FakeResponse(_AGENT_IFACES)
        return _FakeResponse(None, status_code=404)

    def post(self, url, data=None, timeout=None, **kwargs):
        self.calls.append("POST " + url)
        return _FakeResponse({"ticket": "TICKET", "CSRFPreventionToken": "CSRF"})


@pytest.fixture
def fake_requests(monkeypatch):
    mod = types.ModuleType("requests")
    mod.Session = _FakeSession
    pkgs = types.SimpleNamespace(urllib3=types.SimpleNamespace(disable_warnings=lambda *a: None))
    mod.packages = pkgs
    monkeypatch.setitem(sys.modules, "requests", mod)
    return mod


def test_missing_requests_raises_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", None)  # force ImportError
    c = ProxmoxCollector("pve.example.com", token_id="u@pam!t", token_secret="s")
    with pytest.raises(CollectorError) as ei:
        c.test_connection()
    assert "pip install 'fleetview[proxmox]'" in str(ei.value)


def test_token_auth_header(fake_requests):
    c = ProxmoxCollector("pve.example.com", token_id="root@pam!mon", token_secret="secret")
    sess = c._connect()
    assert sess.headers["Authorization"] == "PVEAPIToken=root@pam!mon=secret"


def test_requires_credentials(fake_requests):
    c = ProxmoxCollector("pve.example.com")
    with pytest.raises(CollectorError):
        c._connect()


def test_collect_maps_qemu_and_lxc(fake_requests):
    c = ProxmoxCollector("pve.example.com", token_id="root@pam!mon", token_secret="s")
    result = c.collect()

    assert result.provider.kind is ProviderKind.PROXMOX
    assert result.provider.instance == "pve.example.com"
    assert result.provider.node_count == 2
    assert result.provider.extra["cluster_nodes"] == ["pve1", "pve2"]

    by_name = {n.name: n for n in result.nodes}
    assert set(by_name) == {"web01", "ct-redis"}

    vm = by_name["web01"]
    assert vm.kind is NodeKind.VM
    assert vm.power_state is PowerState.RUNNING
    assert vm.source.provider is ProviderKind.PROXMOX
    assert vm.source.native_id == "100"
    assert vm.source.native_type == "qemu"
    assert vm.id == "proxmox:pve.example.com:100"
    # compute: cores*sockets = 4, memory 8192 MiB
    assert vm.compute.vcpus == 4
    assert vm.compute.memory_mb == 8192
    assert vm.compute.firmware == "ovmf"
    # placement
    assert vm.placement.host == "pve1"
    assert vm.placement.zone == "pve1"
    assert vm.placement.resource_pool == "prod"
    # disk: scsi0 32G, cdrom skipped
    assert len(vm.disks) == 1
    assert vm.disks[0].label == "scsi0"
    assert vm.disks[0].size_gb == 32.0
    assert vm.disks[0].backing == "local-lvm"
    # nic + vlan + mac, primary IP from guest agent
    assert vm.nics[0].mac == "AA:BB:CC:DD:EE:FF"
    assert vm.nics[0].network == "vmbr0"
    assert vm.nics[0].vlan == 10
    assert vm.primary_ip == "192.168.1.10"
    # tags from pool + per-guest tags
    assert vm.tags["pool"] == "prod"
    assert vm.tags["tag:web"] == "true"
    assert vm.tags["tag:public"] == "true"
    assert vm.annotations == "frontend"
    # raw fidelity
    assert vm.source.raw["config"]["scsi0"].startswith("local-lvm")

    ct = by_name["ct-redis"]
    assert ct.kind is NodeKind.CONTAINER
    assert ct.disks[0].label == "rootfs"
    assert ct.disks[0].size_gb == 8.0
    # LXC primary IP parsed from static net config
    assert ct.primary_ip == "10.0.0.50"
    assert ct.tags["pool"] == "infra"
    assert ct.compute.memory_mb == 1024


def test_bad_guest_becomes_warning(fake_requests, monkeypatch):
    c = ProxmoxCollector("pve.example.com", token_id="root@pam!mon", token_secret="s")
    orig = c._guest_to_node

    def boom(res, vmtype):
        if res.get("vmid") == 100:
            raise RuntimeError("kaboom")
        return orig(res, vmtype)

    monkeypatch.setattr(c, "_guest_to_node", boom)
    result = c.collect()
    assert len(result.nodes) == 1  # only the LXC survived
    assert any("kaboom" in w for w in result.warnings)
