"""FleetView — a holistic, point-in-time picture of an environment.

Connects to vCenter/ESXi, Proxmox, AWS, and GCP; introspects every box; builds a unified,
provider-agnostic model of the fleet; and from it can reproduce configs and analyze cost &
improvements. Not a live-metrics tool — it captures structure, not time-series.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .models import Fleet, Node, Provider, ProviderKind

__all__ = ["Fleet", "Node", "Provider", "ProviderKind", "__version__"]
