"""FleetView deep inspection (Milestone 5): in-guest discovery over SSH.

The hypervisor / cloud collectors see a VM from the outside; deep inspection
logs into the guest to discover what it is actually running and what data flows
in and out, populating the model fields the outside view cannot fill.
"""

from __future__ import annotations

from .collect import enrich_node
from .ssh import SSHInspector

__all__ = ["SSHInspector", "enrich_node"]
