"""Unit tests for the AWS collector — boto3 is faked via an injected module.

A fake boto3.Session returns fake clients (ec2/sts/rds) whose methods return canned dicts,
including paginators. We then assert the mapping into the unified Node model.
"""
from __future__ import annotations

import sys
import types

import pytest

from fleetview.collectors.aws import AWSCollector
from fleetview.collectors.base import CollectorError
from fleetview.models import DiskType, NodeKind, PowerState, ProviderKind

# ---- canned EC2 / RDS payloads ------------------------------------------------

_INSTANCE = {
    "InstanceId": "i-0abc123",
    "InstanceType": "t3.large",
    "Architecture": "x86_64",
    "BootMode": "uefi",
    "PlatformDetails": "Linux/UNIX",
    "State": {"Name": "running"},
    "Placement": {"AvailabilityZone": "us-east-1a", "GroupName": "", "HostId": None},
    "Tags": [{"Key": "Name", "Value": "api-server"}, {"Key": "env", "Value": "prod"}],
    "BlockDeviceMappings": [
        {"DeviceName": "/dev/sda1", "Ebs": {"VolumeId": "vol-111"}},
    ],
    "NetworkInterfaces": [
        {
            "NetworkInterfaceId": "eni-1",
            "MacAddress": "0a:1b:2c:3d:4e:5f",
            "SubnetId": "subnet-aaa",
            "VpcId": "vpc-bbb",
            "Groups": [{"GroupId": "sg-123"}, {"GroupId": "sg-456"}],
            "Attachment": {"Status": "attached"},
            "PrivateIpAddresses": [
                {"PrivateIpAddress": "10.0.1.5",
                 "Association": {"PublicIp": "54.1.2.3"}},
            ],
        }
    ],
}

_VOLUME = {
    "VolumeId": "vol-111", "Size": 100, "VolumeType": "gp3",
    "Encrypted": True, "Iops": 3000,
}

_TYPE_INFO = {
    "InstanceTypes": [
        {"InstanceType": "t3.large",
         "VCpuInfo": {"DefaultVCpus": 2},
         "MemoryInfo": {"SizeInMiB": 8192}},
    ]
}

_DB = {
    "DBInstanceIdentifier": "prod-pg",
    "DBInstanceArn": "arn:aws:rds:us-east-1:111122223333:db:prod-pg",
    "DBInstanceClass": "db.t3.medium",
    "DBInstanceStatus": "available",
    "Engine": "postgres",
    "AvailabilityZone": "us-east-1b",
    "AllocatedStorage": 50,
    "StorageType": "gp2",
    "StorageEncrypted": True,
    "Endpoint": {"Address": "prod-pg.abc.us-east-1.rds.amazonaws.com", "Port": 5432},
    "TagList": [{"Key": "team", "Value": "data"}],
}


class _Paginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        return iter(self._pages)


class _FakeEC2:
    def __init__(self):
        self.type_calls = 0

    def get_paginator(self, name):
        if name == "describe_instances":
            return _Paginator([{"Reservations": [{"Instances": [_INSTANCE]}]}])
        if name == "describe_volumes":
            return _Paginator([{"Volumes": [_VOLUME]}])
        raise AssertionError(f"unexpected paginator {name}")

    def describe_instance_types(self, InstanceTypes=None):
        self.type_calls += 1
        return _TYPE_INFO


class _FakeSTS:
    def get_caller_identity(self):
        return {"Account": "111122223333", "Arn": "arn:aws:iam::111122223333:user/x"}


class _FakeRDS:
    def get_paginator(self, name):
        assert name == "describe_db_instances"
        return _Paginator([{"DBInstances": [_DB]}])


class _FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.ec2 = _FakeEC2()

    def client(self, service):
        if service == "ec2":
            return self.ec2
        if service == "sts":
            return _FakeSTS()
        if service == "rds":
            return _FakeRDS()
        raise AssertionError(f"unexpected client {service}")


@pytest.fixture
def fake_boto3(monkeypatch):
    mod = types.ModuleType("boto3")
    mod.Session = _FakeSession
    monkeypatch.setitem(sys.modules, "boto3", mod)
    return mod


def test_missing_boto3_raises_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)  # force ImportError
    c = AWSCollector("us-east-1")
    with pytest.raises(CollectorError) as ei:
        c.test_connection()
    assert "pip install 'fleetview[aws]'" in str(ei.value)


def test_collect_maps_ec2_and_rds(fake_boto3):
    c = AWSCollector("us-east-1")
    result = c.collect()

    assert result.provider.kind is ProviderKind.AWS
    assert result.provider.instance == "111122223333"
    assert result.provider.extra["account_id"] == "111122223333"
    assert result.provider.node_count == 2

    by_kind = {}
    for n in result.nodes:
        by_kind.setdefault(n.kind, []).append(n)

    vm = by_kind[NodeKind.VM][0]
    assert vm.name == "api-server"  # from Name tag
    assert vm.id == "aws:111122223333:i-0abc123"
    assert vm.power_state is PowerState.RUNNING
    assert vm.compute.instance_type == "t3.large"
    assert vm.compute.vcpus == 2
    assert vm.compute.memory_mb == 8192
    assert vm.compute.architecture == "x86_64"
    assert vm.placement.region == "us-east-1"
    assert vm.placement.zone == "us-east-1a"
    # disk from EBS volume lookup
    assert vm.disks[0].size_gb == 100
    assert vm.disks[0].disk_type is DiskType.SSD
    assert vm.disks[0].encrypted is True
    assert vm.disks[0].iops == 3000
    assert vm.disks[0].path == "vol-111"
    # nic: private + public ips, mac, subnet, sgs
    nic = vm.nics[0]
    assert nic.ips == ["10.0.1.5", "54.1.2.3"]
    assert vm.primary_ip == "10.0.1.5"
    assert nic.mac == "0a:1b:2c:3d:4e:5f"
    assert nic.network == "subnet-aaa"
    assert nic.switch == "vpc-bbb"
    assert set(nic.security_groups) == {"sg-123", "sg-456"}
    assert nic.connected is True
    # tags
    assert vm.tags["env"] == "prod"
    # raw fidelity
    assert vm.source.raw["InstanceId"] == "i-0abc123"

    db = by_kind[NodeKind.MANAGED][0]
    assert db.name == "prod-pg"
    assert db.compute.instance_type == "db.t3.medium"
    assert db.power_state is PowerState.RUNNING
    assert db.disks[0].size_gb == 50
    assert db.disks[0].encrypted is True
    assert db.nics[0].ips == ["prod-pg.abc.us-east-1.rds.amazonaws.com"]
    assert db.annotations == "postgres"
    assert db.source.native_type == "rds:db"


def test_instance_type_lookup_is_cached(fake_boto3):
    c = AWSCollector("us-east-1")
    c.collect()
    # only one EC2 instance type encountered -> exactly one describe_instance_types call
    assert c._sess().ec2.type_calls == 1
    # cache is populated
    assert c._type_cache["t3.large"] == (2, 8192)


def test_rds_failure_does_not_break_scan(fake_boto3, monkeypatch):
    c = AWSCollector("us-east-1")

    def boom(instance_key, warnings):
        raise RuntimeError("rds exploded")

    monkeypatch.setattr(c, "_rds_nodes", boom)
    result = c.collect()
    assert any(n.kind is NodeKind.VM for n in result.nodes)
    assert all(n.kind is not NodeKind.MANAGED for n in result.nodes)
    assert any("rds exploded" in w for w in result.warnings)
