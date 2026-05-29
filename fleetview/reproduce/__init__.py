"""Reproduce engine — turn a Node into the config needed to rebuild it (IaC).

Milestone 3. The interface is defined now so collectors and the model are designed with
reproduction in mind. A `Reproducer` takes a Node and emits one or more `Artifact`s
(Terraform, Ansible, cloud-init, Dockerfile/compose) that recreate it — ideally on a
*different* platform than the original (that's the cross-platform value).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import Node, ProviderKind


@dataclass
class Artifact:
    """One generated config file."""

    filename: str
    content: str
    kind: str  # terraform | ansible | cloud-init | dockerfile | compose


class Reproducer(ABC):
    """Generates config to rebuild a Node, targeting some platform."""

    target: ProviderKind

    @abstractmethod
    def reproduce(self, node: Node) -> list[Artifact]:
        """Emit artifacts that recreate `node` on `self.target`."""


# NOTE: concrete reproducers (TerraformAWSReproducer, AnsibleReproducer, ...) land in M3.
