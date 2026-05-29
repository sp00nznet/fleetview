from __future__ import annotations

from fleetview.models import (
    Compute,
    Disk,
    ListeningPort,
    Node,
    NodeKind,
    OSFamily,
    OSInfo,
    Package,
    Service,
    SoftwareInventory,
    SourceRef,
    ProviderKind,
)
from fleetview.reproduce import available_targets, get_reproducer


def _node():
    return Node(
        id="aws:acct:web01",
        name="web01",
        kind=NodeKind.VM,
        compute=Compute(vcpus=4, memory_mb=8192, instance_type="t3.large"),
        disks=[Disk(label="root", size_gb=80), Disk(label="data", size_gb=200)],
        os=OSInfo(family=OSFamily.LINUX, distro="Ubuntu 22.04"),
        software=SoftwareInventory(
            packages=[Package(name="nginx", manager="apt"), Package(name="postgresql-client", manager="apt")],
            services=[Service(name="nginx", state="running")],
            listeners=[ListeningPort(port=443), ListeningPort(port=80)],
        ),
        source=SourceRef(provider=ProviderKind.AWS, provider_instance="acct", native_id="web01"),
    )


def test_registry_targets():
    assert set(available_targets()) >= {"terraform-aws", "terraform-vsphere", "ansible"}


def test_terraform_aws_emits_main_with_shape_and_disk():
    arts = get_reproducer("terraform-aws").reproduce(_node())
    files = {a.filename: a.content for a in arts}
    assert "main.tf" in files and "provider.tf" in files
    main = files["main.tf"]
    assert "t3.large" in main
    assert "aws_instance" in main
    assert "volume_size = 200" in main or "volume_size = 80" in main
    # observed ports become ingress rules
    assert "from_port   = 443" in main


def test_terraform_vsphere_emits_cpu_memory():
    arts = get_reproducer("terraform-vsphere").reproduce(_node())
    main = next(a.content for a in arts if a.filename == "main.tf")
    assert "num_cpus         = 4" in main
    assert "memory           = 8192" in main
    assert "vsphere_virtual_machine" in main


def test_ansible_lists_packages_and_services():
    arts = get_reproducer("ansible").reproduce(_node())
    site = next(a.content for a in arts if a.filename == "site.yml")
    assert "nginx" in site
    assert "postgresql-client" in site
    assert "ansible.builtin.apt" in site
    assert "443" in site


def test_unknown_target_raises():
    try:
        get_reproducer("nope")
    except ValueError as e:
        assert "Unknown reproduce target" in str(e)
    else:
        raise AssertionError("expected ValueError")
