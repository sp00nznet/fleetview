"""Orchestration for FleetView deep inspection.

:func:`enrich_node` opens an :class:`SSHInspector` against a node, runs a
battery of discovery commands, feeds the raw output through the pure parsers in
:mod:`fleetview.inspect.probes`, and populates ``node.software`` /
``node.flows``.

Every probe is wrapped in try/except so a missing command (``docker`` not
installed, ``rpm`` absent on Debian, etc.) degrades gracefully instead of
aborting the whole inspection.
"""

from __future__ import annotations

from typing import List, Optional

from ..models.fleet import Node
from ..models.software import ConfigFile, SoftwareInventory
from . import probes
from .ssh import SSHInspector

# Known service config locations (target path -> owning service label).
_CONFIG_TARGETS = [
    ("/etc/ssh/sshd_config", "openssh"),
    ("/etc/nginx", "nginx"),
    ("/etc/apache2", "apache"),
    ("/etc/httpd", "apache"),
    ("/etc/postgresql", "postgresql"),
    ("/etc/mysql", "mysql"),
    ("/etc/redis", "redis"),
    ("/etc/docker/daemon.json", "docker"),
]


def _safe(inspector: SSHInspector, cmd: str) -> Optional[str]:
    """Run a command, returning stdout on success (exit 0) else ``None``."""
    try:
        out, _err, code = inspector.run(cmd)
    except Exception:
        return None
    if code != 0:
        return None
    return out


def _collect_config_files(
    inspector: SSHInspector, capture_contents: bool
) -> List[ConfigFile]:
    """Collect metadata (and optionally contents) for known config files.

    Uses ``find`` to enumerate regular files under each target, then ``stat``
    for owner/group/mode/size and ``sha256sum`` for a content hash.
    """
    files: List[ConfigFile] = []
    seen = set()
    for target, belongs_to in _CONFIG_TARGETS:
        listing = _safe(inspector, f"find {target} -maxdepth 3 -type f 2>/dev/null")
        if not listing:
            continue
        for path in listing.splitlines():
            path = path.strip()
            if not path or path in seen:
                continue
            seen.add(path)
            cf = ConfigFile(path=path, belongs_to=belongs_to)
            stat_out = _safe(inspector, f"stat -c '%U|%G|%a|%s' {path} 2>/dev/null")
            if stat_out:
                cols = stat_out.strip().splitlines()[0].split("|")
                if len(cols) == 4:
                    cf.owner = cols[0] or None
                    cf.group = cols[1] or None
                    cf.mode = cols[2] or None
                    try:
                        cf.size_bytes = int(cols[3])
                    except ValueError:
                        pass
            sha_out = _safe(inspector, f"sha256sum {path} 2>/dev/null")
            if sha_out:
                cf.sha256 = sha_out.strip().split()[0]
            if capture_contents:
                contents = _safe(inspector, f"cat {path} 2>/dev/null")
                if contents is not None:
                    cf.content = contents
            files.append(cf)
    return files


def enrich_node(
    node: Node,
    *,
    host: Optional[str] = None,
    username: str,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
    port: int = 22,
    sudo: bool = False,
    capture_config_contents: bool = False,
) -> Node:
    """Deep-inspect ``node`` over SSH and populate its inventory in place.

    Parameters
    ----------
    node:
        The :class:`~fleetview.models.fleet.Node` to enrich.  Mutated in place
        (and also returned for convenience).
    host:
        SSH target; defaults to ``node.primary_ip``.  Raises ``ValueError`` if
        neither is set.
    username, key_path, password, port, sudo:
        Passed through to :class:`SSHInspector`.
    capture_config_contents:
        When True, the full text of discovered config files is captured (not
        just metadata + sha256).
    """
    target = host or node.primary_ip
    if not target:
        raise ValueError(
            f"No SSH host for node {node.id!r}: pass host= or set node.primary_ip"
        )

    inv = SoftwareInventory()

    with SSHInspector(
        host=target,
        username=username,
        key_path=key_path,
        password=password,
        port=port,
        sudo=sudo,
    ) as inspector:
        # --- Packages -----------------------------------------------------
        out = _safe(inspector, "dpkg -l")
        if out:
            try:
                inv.packages.extend(probes.parse_packages_dpkg(out))
            except Exception:
                pass
        out = _safe(
            inspector, "rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\n'"
        )
        if out:
            try:
                inv.packages.extend(probes.parse_packages_rpm(out))
            except Exception:
                pass
        out = _safe(inspector, "pip3 list 2>/dev/null || pip list 2>/dev/null")
        if out:
            try:
                inv.packages.extend(probes.parse_packages_pip(out))
            except Exception:
                pass

        # --- Services -----------------------------------------------------
        out = _safe(
            inspector,
            "systemctl list-units --type=service --all --no-pager --no-legend",
        )
        if out:
            try:
                inv.services.extend(probes.parse_services_systemctl(out))
            except Exception:
                pass

        # --- Listeners ----------------------------------------------------
        out = _safe(inspector, "ss -tlnp")
        if out:
            try:
                inv.listeners.extend(probes.parse_listeners_ss(out))
            except Exception:
                pass

        # --- Processes ----------------------------------------------------
        out = _safe(inspector, "ps aux")
        if out:
            try:
                inv.processes.extend(probes.parse_processes_ps(out))
            except Exception:
                pass

        # --- Containers ---------------------------------------------------
        out = _safe(inspector, "docker ps --format '{{json .}}'")
        if out:
            try:
                inv.containers.extend(probes.parse_docker_ps(out))
            except Exception:
                pass

        # --- Config files -------------------------------------------------
        try:
            inv.config_files.extend(
                _collect_config_files(inspector, capture_config_contents)
            )
        except Exception:
            pass

        # --- Flows: mounts ------------------------------------------------
        fstab = _safe(inspector, "cat /etc/fstab") or ""
        mounts = _safe(inspector, "mount") or ""
        new_flows = []
        try:
            new_flows.extend(probes.parse_mounts(fstab, mounts))
        except Exception:
            pass

        # --- Flows: established TCP connections ---------------------------
        out = _safe(inspector, "ss -tnp")
        if out:
            try:
                new_flows.extend(probes.parse_tcp_connections_ss(out))
            except Exception:
                pass

    # --- Fingerprints (pure, from gathered inventory) ---------------------
    try:
        inv.fingerprints.extend(probes.fingerprint(inv))
    except Exception:
        pass

    inv.deep_inspected = True
    node.software = inv
    node.flows.extend(new_flows)
    return node
