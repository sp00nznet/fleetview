"""Provider collectors. Each adapter maps a platform onto the unified data model.

Registry pattern: collectors register their ProviderKind so the CLI can dispatch by name and
so new providers (proxmox/aws/gcp) drop in without touching the CLI.
"""
from __future__ import annotations

from .base import Collector, CollectorError, CollectResult

#: provider name -> collector class. Populated lazily to avoid importing heavy SDKs
#: (pyvmomi/boto3/...) unless a provider is actually used.
_REGISTRY: dict[str, str] = {
    "vmware": "fleetview.collectors.vmware:VMwareCollector",
}


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def load_collector_class(provider: str) -> type[Collector]:
    """Import and return the collector class for a provider name."""
    if provider not in _REGISTRY:
        raise CollectorError(
            f"Unknown provider '{provider}'. Available: {', '.join(available_providers())}"
        )
    module_path, _, class_name = _REGISTRY[provider].partition(":")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


__all__ = [
    "Collector",
    "CollectorError",
    "CollectResult",
    "available_providers",
    "load_collector_class",
]
