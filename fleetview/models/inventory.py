"""Inventory primitives: a Node and its hardware-shaped facts (compute, storage, network).

These describe *what a box is*, independent of provider. Collectors map their native objects
onto these; downstream consumers never see provider-specific shapes here.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import DiskType, NodeKind, OSFamily, PowerState, ProviderKind


class Placement(BaseModel):
    """Where the node physically/logically sits."""

    provider: ProviderKind = ProviderKind.UNKNOWN
    host: Optional[str] = Field(None, description="Hypervisor / physical host the node runs on")
    cluster: Optional[str] = None
    resource_pool: Optional[str] = None
    datacenter: Optional[str] = None
    region: Optional[str] = Field(None, description="Cloud region, e.g. us-east-1")
    zone: Optional[str] = Field(None, description="Availability zone / hypervisor node")
    folder: Optional[str] = Field(None, description="vCenter folder path / GCP project / etc.")


class Compute(BaseModel):
    vcpus: Optional[int] = None
    cores_per_socket: Optional[int] = None
    sockets: Optional[int] = None
    memory_mb: Optional[int] = None
    cpu_model: Optional[str] = None
    architecture: Optional[str] = Field(None, description="x86_64, arm64, ...")
    firmware: Optional[str] = Field(None, description="bios | efi")
    instance_type: Optional[str] = Field(
        None, description="Cloud shape, e.g. t3.large / e2-standard-4 (None for on-prem)"
    )


class Disk(BaseModel):
    label: Optional[str] = None
    size_gb: Optional[float] = None
    disk_type: DiskType = DiskType.UNKNOWN
    backing: Optional[str] = Field(None, description="datastore/volume/pool the disk lives on")
    path: Optional[str] = Field(None, description="backing file path / volume id")
    provisioning: Optional[str] = Field(None, description="thin | thick | eager-zeroed | ...")
    encrypted: Optional[bool] = None
    iops: Optional[int] = None


class Nic(BaseModel):
    label: Optional[str] = None
    mac: Optional[str] = None
    ips: list[str] = Field(default_factory=list)
    vlan: Optional[int] = None
    network: Optional[str] = Field(None, description="port group / VPC subnet / bridge name")
    switch: Optional[str] = Field(None, description="vSwitch / dvSwitch / VPC")
    security_groups: list[str] = Field(default_factory=list)
    connected: Optional[bool] = None


class OSInfo(BaseModel):
    family: OSFamily = OSFamily.UNKNOWN
    distro: Optional[str] = Field(None, description="ubuntu / rhel / windows-server / ...")
    version: Optional[str] = None
    kernel: Optional[str] = None
    hostname: Optional[str] = None
    # Convenience flag the analyzer can set; collectors usually leave it None.
    end_of_life: Optional[bool] = None


class SourceRef(BaseModel):
    """Pointer back to the provider object + raw facts, for fidelity and re-derivation.

    We keep the raw provider payload so later milestones can extract more without re-scanning.
    """

    provider: ProviderKind
    provider_instance: Optional[str] = Field(
        None, description="Which connection produced this (e.g. vcenter hostname / aws account id)"
    )
    native_id: Optional[str] = Field(None, description="MoRef / instance-id / vmid / etc.")
    native_type: Optional[str] = Field(None, description="VirtualMachine / ec2:instance / qemu / ...")
    raw: dict = Field(
        default_factory=dict,
        description="Raw provider facts, lightly normalized. Not schema-stable; for fidelity only.",
    )
