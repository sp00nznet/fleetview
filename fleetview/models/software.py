"""What a box is *running*: packages, services, processes, listening ports, containers.

Milestone 1's VMware collector populates only what the hypervisor exposes (e.g. VMware Tools
guest info: hostname, IPs, OS). Deep software inventory arrives with in-guest inspection
(SSH / guest agent) in a later milestone — but the shape is defined now so the frontend and
analyzer can be built against it.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .enums import ConfidenceLevel


class Package(BaseModel):
    name: str
    version: Optional[str] = None
    manager: Optional[str] = Field(None, description="apt | yum | apk | pip | npm | msi | ...")


class Service(BaseModel):
    """A managed service unit (systemd unit, Windows service, etc.)."""

    name: str
    state: Optional[str] = Field(None, description="running | stopped | enabled | disabled")
    description: Optional[str] = None
    exec_path: Optional[str] = None


class Process(BaseModel):
    pid: Optional[int] = None
    name: Optional[str] = None
    cmdline: Optional[str] = None
    user: Optional[str] = None


class ListeningPort(BaseModel):
    port: int
    protocol: str = Field("tcp", description="tcp | udp")
    address: Optional[str] = Field(None, description="bind address, e.g. 0.0.0.0 / 127.0.0.1")
    process: Optional[str] = None


class ContainerInfo(BaseModel):
    """A container running *inside* this node (e.g. Docker on a VM) — distinct from a node
    that *is* a container."""

    id: Optional[str] = None
    name: Optional[str] = None
    image: Optional[str] = None
    image_digest: Optional[str] = None
    runtime: Optional[str] = Field(None, description="docker | containerd | podman | ...")
    ports: list[ListeningPort] = Field(default_factory=list)
    state: Optional[str] = None


class AppFingerprint(BaseModel):
    """A higher-level identification of an application stack running on the node.

    Produced by heuristics over packages/services/ports (e.g. 'nginx + php-fpm + mysql ->
    LAMP web app'). Used by the analyzer for modernization/cost recommendations.
    """

    name: str = Field(..., description="e.g. nginx, postgresql, kafka, jenkins")
    category: Optional[str] = Field(None, description="webserver | database | queue | ci | ...")
    version: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.INFERRED
    evidence: list[str] = Field(
        default_factory=list, description="signals that led to this fingerprint"
    )


class SoftwareInventory(BaseModel):
    """Everything we know about what's running on a node."""

    packages: list[Package] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    processes: list[Process] = Field(default_factory=list)
    listeners: list[ListeningPort] = Field(default_factory=list)
    containers: list[ContainerInfo] = Field(default_factory=list)
    fingerprints: list[AppFingerprint] = Field(default_factory=list)
    # True once an in-guest inspection has actually run; False means "hypervisor view only".
    deep_inspected: bool = False
