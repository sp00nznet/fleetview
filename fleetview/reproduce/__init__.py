"""Reproduce engine — turn a Node into the config needed to rebuild it (IaC).

A `Reproducer` takes a Node and emits one or more `Artifact`s (Terraform, Ansible, ...) that
recreate it — ideally on a *different* platform than the original (that's the cross-platform
value). Generators emit text only; they never shell out to terraform/ansible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Node


@dataclass
class Artifact:
    """One generated config file."""

    filename: str
    content: str
    kind: str  # terraform | ansible | cloud-init | dockerfile | compose


class Reproducer(ABC):
    """Generates config to rebuild a Node, targeting some platform/tool."""

    #: short target key, e.g. "terraform-aws"
    target: str

    @abstractmethod
    def reproduce(self, node: Node) -> list[Artifact]:
        """Emit artifacts that recreate `node`."""


def available_targets() -> list[str]:
    return sorted(_REGISTRY)


def get_reproducer(target: str) -> Reproducer:
    """Factory: return a Reproducer for a target key (e.g. 'terraform-aws')."""
    if target not in _REGISTRY:
        raise ValueError(
            f"Unknown reproduce target '{target}'. Available: {', '.join(available_targets())}"
        )
    return _REGISTRY[target]()


# Imported at the bottom to avoid an import cycle (concrete reproducers import Artifact/Reproducer).
from .ansible import AnsibleReproducer  # noqa: E402
from .terraform import TerraformAWSReproducer, TerraformVSphereReproducer  # noqa: E402

_REGISTRY: dict[str, type[Reproducer]] = {
    "terraform-aws": TerraformAWSReproducer,
    "terraform-vsphere": TerraformVSphereReproducer,
    "ansible": AnsibleReproducer,
}

__all__ = [
    "Artifact",
    "Reproducer",
    "available_targets",
    "get_reproducer",
    "TerraformAWSReproducer",
    "TerraformVSphereReproducer",
    "AnsibleReproducer",
]
