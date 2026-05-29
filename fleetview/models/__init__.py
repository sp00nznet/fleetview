"""FleetView unified data model.

The single source of truth for how an environment is represented. Import everything from here:

    from fleetview.models import Fleet, Node, ProviderKind
"""
from __future__ import annotations

from .analysis import CostEstimate, Finding, NodeAnalysis
from .enums import (
    ConfidenceLevel,
    DiskType,
    FindingCategory,
    FindingSeverity,
    FlowMechanism,
    NodeKind,
    OSFamily,
    PowerState,
    ProviderKind,
)
from .fleet import Fleet, FleetMeta, Node, Provider
from .flows import DataFlow, Endpoint
from .inventory import Compute, Disk, Nic, OSInfo, Placement, SourceRef
from .software import (
    AppFingerprint,
    ConfigFile,
    ContainerInfo,
    ListeningPort,
    Package,
    Process,
    Service,
    SoftwareInventory,
)

__all__ = [
    # roots
    "Fleet",
    "FleetMeta",
    "Node",
    "Provider",
    # inventory
    "Placement",
    "Compute",
    "Disk",
    "Nic",
    "OSInfo",
    "SourceRef",
    # software
    "SoftwareInventory",
    "Package",
    "Service",
    "Process",
    "ListeningPort",
    "ContainerInfo",
    "ConfigFile",
    "AppFingerprint",
    # flows
    "DataFlow",
    "Endpoint",
    # analysis
    "NodeAnalysis",
    "Finding",
    "CostEstimate",
    # enums
    "ProviderKind",
    "NodeKind",
    "PowerState",
    "OSFamily",
    "DiskType",
    "FlowMechanism",
    "FindingSeverity",
    "FindingCategory",
    "ConfidenceLevel",
]
