"""Pricing tables + spec→instance matching for cross-platform cost estimates.

Pricing is approximate on-demand Linux list price (us-east-1 / us-central1 equivalents),
ported from whatdoesthisboxdo's cost_estimator. It is intentionally static data — refresh
periodically; live pricing APIs are a later enhancement. Proxmox/on-prem uses an amortized
hardware model since there's no list price.

All figures are USD/month (730 hours).
"""
from __future__ import annotations

from typing import Optional

from ..models import ProviderKind

HOURS_PER_MONTH = 730

# name -> (vcpu, ram_gb, hourly_usd)
AWS_PRICING: dict[str, tuple[int, float, float]] = {
    "t3.micro": (2, 1, 0.0104),
    "t3.small": (2, 2, 0.0208),
    "t3.medium": (2, 4, 0.0416),
    "t3.large": (2, 8, 0.0832),
    "t3.xlarge": (4, 16, 0.1664),
    "t3.2xlarge": (8, 32, 0.3328),
    "m5.large": (2, 8, 0.096),
    "m5.xlarge": (4, 16, 0.192),
    "m5.2xlarge": (8, 32, 0.384),
    "m5.4xlarge": (16, 64, 0.768),
    "c5.large": (2, 4, 0.085),
    "c5.xlarge": (4, 8, 0.17),
    "c5.2xlarge": (8, 16, 0.34),
    "r5.large": (2, 16, 0.126),
    "r5.xlarge": (4, 32, 0.252),
    "r5.2xlarge": (8, 64, 0.504),
}

GCP_PRICING: dict[str, tuple[int, float, float]] = {
    "e2-micro": (2, 1, 0.0084),
    "e2-small": (2, 2, 0.0168),
    "e2-medium": (2, 4, 0.0335),
    "e2-standard-2": (2, 8, 0.0670),
    "e2-standard-4": (4, 16, 0.1340),
    "e2-standard-8": (8, 32, 0.2680),
    "n2-standard-2": (2, 8, 0.0971),
    "n2-standard-4": (4, 16, 0.1942),
    "n2-standard-8": (8, 32, 0.3884),
    "n2-highmem-4": (4, 32, 0.2620),
}

AZURE_PRICING: dict[str, tuple[int, float, float]] = {
    "B1s": (1, 1, 0.0104),
    "B2s": (2, 4, 0.0416),
    "B2ms": (2, 8, 0.0832),
    "D2s_v3": (2, 8, 0.096),
    "D4s_v3": (4, 16, 0.192),
    "D8s_v3": (8, 32, 0.384),
    "E2s_v3": (2, 16, 0.1262),
    "E4s_v3": (4, 32, 0.2524),
}

# per-GB/month storage
STORAGE_PER_GB = {
    ProviderKind.AWS: 0.08,    # gp3
    ProviderKind.GCP: 0.04,    # pd-standard
    ProviderKind.PROXMOX: 0.0, # bundled into amortized hw model
    ProviderKind.VMWARE: 0.0,
}

_TABLES = {
    ProviderKind.AWS: AWS_PRICING,
    ProviderKind.GCP: GCP_PRICING,
}

# Amortized on-prem cost model (per-unit/month), used for Proxmox/VMware. Rough industry
# rule-of-thumb: hardware + power + cooling + rack, amortized over ~3 years.
ONPREM_PER_VCPU = 3.0
ONPREM_PER_GB_RAM = 1.0
ONPREM_PER_GB_DISK = 0.015


def _find_best_instance(
    table: dict[str, tuple[int, float, float]], vcpus: int, ram_gb: float
) -> tuple[str, float]:
    """Cheapest instance meeting the vcpu+ram requirement (or the biggest if none fits)."""
    candidates = [
        (name, hourly) for name, (cpu, ram, hourly) in table.items() if cpu >= vcpus and ram >= ram_gb
    ]
    if candidates:
        name, hourly = min(candidates, key=lambda x: x[1])
        return name, hourly
    # nothing fits — return the largest shape by vcpu
    name = max(table.items(), key=lambda kv: kv[1][0])[0]
    return name, table[name][2]


def estimate(
    platform: ProviderKind, vcpus: int, memory_mb: int, storage_gb: float = 0.0
) -> tuple[Optional[str], Optional[float], list[str]]:
    """Return (instance_type, monthly_usd, assumptions) for running this spec on `platform`.

    Returns (None, None, [...]) if the platform isn't priceable.
    """
    vcpus = max(int(vcpus or 1), 1)
    ram_gb = round((memory_mb or 0) / 1024, 2) or 1.0

    if platform in _TABLES:
        table = _TABLES[platform]
        inst, hourly = _find_best_instance(table, vcpus, ram_gb)
        compute = hourly * HOURS_PER_MONTH
        storage = storage_gb * STORAGE_PER_GB.get(platform, 0.0)
        assumptions = [
            "on-demand Linux list price",
            f"matched shape {inst} (>= {vcpus} vCPU / {ram_gb} GB)",
            f"compute ${compute:.2f} + storage ${storage:.2f}",
        ]
        return inst, round(compute + storage, 2), assumptions

    if platform in (ProviderKind.PROXMOX, ProviderKind.VMWARE):
        monthly = (
            vcpus * ONPREM_PER_VCPU
            + ram_gb * ONPREM_PER_GB_RAM
            + storage_gb * ONPREM_PER_GB_DISK
        )
        label = f"{vcpus}vcpu/{int(ram_gb)}gb"
        assumptions = [
            "amortized on-prem hardware (~3yr) incl. power/cooling/rack",
            f"${ONPREM_PER_VCPU}/vCPU + ${ONPREM_PER_GB_RAM}/GB RAM + ${ONPREM_PER_GB_DISK}/GB disk",
        ]
        return label, round(monthly, 2), assumptions

    return None, None, ["platform not priceable"]
