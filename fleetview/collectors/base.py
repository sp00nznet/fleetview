"""The Collector contract every provider adapter implements.

A collector connects to one provider instance (a vCenter, a Proxmox cluster, an AWS account,
a GCP project), reads it **read-only**, and emits a `Provider` record plus a list of `Node`s
mapped onto the unified data model. It must never mutate the environment.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Node, Provider, ProviderKind


@dataclass
class CollectResult:
    """What a single collector run returns."""

    provider: Provider
    nodes: list[Node] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class CollectorError(Exception):
    """Raised for fatal collection problems (auth, connectivity)."""


class Collector(ABC):
    """Base class for provider adapters."""

    #: which platform this collector speaks to
    provider_kind: ProviderKind = ProviderKind.UNKNOWN

    @abstractmethod
    def test_connection(self) -> bool:
        """Cheaply verify credentials/connectivity. Returns True or raises CollectorError."""

    @abstractmethod
    def collect(self) -> CollectResult:
        """Perform a full read-only inventory and return Provider + Nodes."""

    @staticmethod
    def make_node_id(provider: ProviderKind, instance: str, native_id: str) -> str:
        """Build the FleetView-stable node id. Stable across snapshots so we can diff."""
        return f"{provider.value}:{instance}:{native_id}"
