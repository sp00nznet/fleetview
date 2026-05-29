"""Pure parsing functions for FleetView deep inspection.

Every function here takes the *raw text* of a command's stdout and returns
typed FleetView model objects.  There is deliberately NO SSH / IO in this
module so the parsers can be unit-tested with captured fixtures.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from ..models.enums import ConfidenceLevel, FlowMechanism
from ..models.flows import DataFlow, Endpoint
from ..models.software import (
    AppFingerprint,
    ContainerInfo,
    ListeningPort,
    Package,
    Process,
    Service,
    SoftwareInventory,
)

__all__ = [
    "parse_packages_dpkg",
    "parse_packages_rpm",
    "parse_packages_pip",
    "parse_services_systemctl",
    "parse_listeners_ss",
    "parse_processes_ps",
    "parse_docker_ps",
    "parse_mounts",
    "parse_tcp_connections_ss",
    "fingerprint",
]


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
def parse_packages_dpkg(text: str) -> List[Package]:
    """Parse ``dpkg -l`` output.

    Installed lines start with ``ii`` and have columns:
    ``ii  name  version  arch  description``.  Only installed (``ii``) rows are
    kept; ``rc`` (config-remains) and header rows are skipped.
    """
    packages: List[Package] = []
    for line in text.splitlines():
        if not line.startswith("ii"):
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        # parts: [status, name, version, arch, (description)]
        name = parts[1]
        # dpkg appends ":arch" to some names (e.g. libc6:amd64).
        name = name.split(":", 1)[0]
        packages.append(Package(name=name, version=parts[2], manager="apt"))
    return packages


def parse_packages_rpm(text: str) -> List[Package]:
    """Parse ``rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\n'``.

    Falls back to plain ``rpm -qa`` output (``name-version-release.arch``) when
    no tab-separated columns are present.
    """
    packages: List[Package] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\t" in line:
            cols = line.split("\t")
            name = cols[0]
            version = cols[1] if len(cols) > 1 and cols[1] else None
            packages.append(Package(name=name, version=version, manager="yum"))
            continue
        # Plain "name-version-release.arch" form.
        name = line
        version: Optional[str] = None
        m = re.match(r"^(.+)-([^-]+-[^-]+)\.[^.]+$", line)
        if m:
            name, version = m.group(1), m.group(2)
        packages.append(Package(name=name, version=version, manager="yum"))
    return packages


def parse_packages_pip(text: str) -> List[Package]:
    """Parse ``pip list`` output (columnar or ``name==version`` freeze form)."""
    packages: List[Package] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("package") and "version" in low:
            continue
        if set(line) <= {"-", " "}:  # separator row
            continue
        if "==" in line:  # freeze format
            name, _, version = line.partition("==")
            packages.append(
                Package(name=name.strip(), version=version.strip(), manager="pip")
            )
            continue
        parts = line.split()
        if len(parts) >= 2:
            packages.append(Package(name=parts[0], version=parts[1], manager="pip"))
        elif parts:
            packages.append(Package(name=parts[0], manager="pip"))
    return packages


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def parse_services_systemctl(text: str) -> List[Service]:
    """Parse ``systemctl list-units --type=service --all --no-legend``.

    Columns: ``UNIT LOAD ACTIVE SUB DESCRIPTION``.  A leading ``●`` bullet
    (used for failed/attention units) is stripped.  ``state`` is set to the
    SUB state (e.g. ``running``/``failed``/``exited``).
    """
    services: List[Service] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("●").strip()
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit = parts[0]
        if not unit.endswith(".service"):
            continue
        name = unit[: -len(".service")]
        services.append(
            Service(
                name=name,
                state=parts[3],  # SUB state: running / dead / failed / exited
                description=parts[4] if len(parts) > 4 else None,
            )
        )
    return services


# ---------------------------------------------------------------------------
# Listening ports
# ---------------------------------------------------------------------------
def _split_addr_port(endpoint: str) -> Optional[Tuple[str, int]]:
    """Split an ``ss`` address column into ``(address, port)``.

    Handles IPv4 ``0.0.0.0:80``, IPv6 ``[::]:80`` / ``[::1]:5432``, and
    wildcard ``*:80`` forms.  Returns ``None`` for wildcard ports.
    """
    endpoint = endpoint.strip()
    if not endpoint:
        return None
    if endpoint.startswith("["):  # IPv6 in brackets
        m = re.match(r"^\[(.*)\]:(\d+|\*)$", endpoint)
        if not m:
            return None
        addr, port = m.group(1), m.group(2)
    else:
        if ":" not in endpoint:
            return None
        addr, _, port = endpoint.rpartition(":")
    if port in ("*", ""):
        return None
    try:
        return addr, int(port)
    except ValueError:
        return None


def _parse_ss_process(field: str) -> Optional[str]:
    """Extract a process name from an ss ``users:(("nginx",pid=1,fd=6))`` field."""
    if not field:
        return None
    m = re.search(r'\("([^"]+)"', field)
    if m:
        return m.group(1)
    return None


def parse_listeners_ss(text: str) -> List[ListeningPort]:
    """Parse ``ss -tlnp`` (TCP listening sockets with process info).

    Columns: ``State Recv-Q Send-Q Local-Address:Port Peer-Address:Port Process``.
    """
    listeners: List[ListeningPort] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("State"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 4:
            continue
        ap = _split_addr_port(parts[3])
        if ap is None:
            continue
        addr, port = ap
        proc_field = parts[5] if len(parts) > 5 else ""
        listeners.append(
            ListeningPort(
                protocol="tcp",
                address=addr,
                port=port,
                process=_parse_ss_process(proc_field),
            )
        )
    return listeners


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
def parse_processes_ps(text: str) -> List[Process]:
    """Parse ``ps aux`` output.

    Columns: ``USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND``.
    The command field becomes ``cmdline`` and its first token ``name``.
    """
    processes: List[Process] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("USER") and "PID" in line:
            continue
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        cmdline = parts[10]
        # Derive a short name from the command's first token (basename).
        first = cmdline.split()[0] if cmdline.split() else cmdline
        name = first.rsplit("/", 1)[-1].rstrip(":")
        processes.append(
            Process(pid=pid, user=parts[0], cmdline=cmdline, name=name or None)
        )
    return processes


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
def _parse_docker_ports(ports_field: str) -> List[ListeningPort]:
    """Turn a docker ``Ports`` string into typed :class:`ListeningPort` objects.

    Example input: ``"0.0.0.0:80->80/tcp, 6379/tcp"``.
    """
    result: List[ListeningPort] = []
    for chunk in (ports_field or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        proto = "tcp"
        if "/" in chunk:
            chunk_no_proto, _, proto = chunk.rpartition("/")
        else:
            chunk_no_proto = chunk
        proto = proto or "tcp"
        # Form: host:hostport->containerport  OR  containerport
        target = chunk_no_proto
        address = None
        if "->" in chunk_no_proto:
            left, _, right = chunk_no_proto.partition("->")
            target = right
            ap = _split_addr_port(left)
            if ap is not None:
                address = ap[0]
        m = re.search(r"(\d+)$", target)
        if not m:
            continue
        result.append(
            ListeningPort(port=int(m.group(1)), protocol=proto, address=address)
        )
    return result


def parse_docker_ps(text: str) -> List[ContainerInfo]:
    """Parse ``docker ps --format '{{json .}}'`` (one JSON object per line)."""
    containers: List[ContainerInfo] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        containers.append(
            ContainerInfo(
                id=str(obj.get("ID") or obj.get("Id") or "") or None,
                image=str(obj.get("Image") or "") or None,
                name=obj.get("Names") or obj.get("Name") or None,
                runtime="docker",
                state=obj.get("Status") or obj.get("State") or None,
                ports=_parse_docker_ports(obj.get("Ports") or ""),
            )
        )
    return containers


# ---------------------------------------------------------------------------
# Mounts -> DataFlow
# ---------------------------------------------------------------------------
_NFS_FSTYPES = {"nfs", "nfs4"}
_CIFS_FSTYPES = {"cifs", "smbfs", "smb", "smb3"}


def _network_mount_to_flow(
    spec: str, mountpoint: str, fstype: str, evidence: str
) -> Optional[DataFlow]:
    fstype_l = fstype.lower()
    if fstype_l in _NFS_FSTYPES:
        mechanism = FlowMechanism.NFS_MOUNT
    elif fstype_l in _CIFS_FSTYPES:
        mechanism = FlowMechanism.SMB_SHARE
    else:
        return None

    host: Optional[str] = None
    export: Optional[str] = None
    if mechanism is FlowMechanism.NFS_MOUNT:
        # NFS spec: server:/export
        if ":" in spec:
            host, _, export = spec.partition(":")
        else:
            export = spec
    else:
        # CIFS spec: //server/share
        m = re.match(r"^//([^/]+)/(.*)$", spec)
        if m:
            host, export = m.group(1), m.group(2)
        else:
            export = spec

    return DataFlow(
        mechanism=mechanism,
        direction="bidirectional",
        peer=Endpoint(address=host, label=spec),
        detail=f"{export} -> {mountpoint}" if export else mountpoint,
        confidence=ConfidenceLevel.OBSERVED,
        evidence=[evidence],
    )


def parse_mounts(fstab_text: str, mount_text: str) -> List[DataFlow]:
    """Discover NFS/CIFS mounts as :class:`DataFlow` edges.

    Reads both ``/etc/fstab`` (declared mounts) and ``mount`` output (active
    mounts), de-duplicating on ``(spec, mountpoint)``.
    """
    flows: List[DataFlow] = []
    seen = set()

    # /etc/fstab: spec mountpoint fstype options ...
    for raw in (fstab_text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        spec, mountpoint, fstype = parts[0], parts[1], parts[2]
        flow = _network_mount_to_flow(
            spec, mountpoint, fstype, evidence=f"fstab: {line}"
        )
        if flow is not None:
            key = (spec, mountpoint)
            if key not in seen:
                seen.add(key)
                flows.append(flow)

    # mount output: "spec on mountpoint type fstype (options)"
    pattern = re.compile(r"^(.+?) on (.+?) type (\S+) \((.*)\)")
    for raw in (mount_text or "").splitlines():
        m = pattern.match(raw.strip())
        if not m:
            continue
        spec, mountpoint, fstype = m.group(1), m.group(2), m.group(3)
        flow = _network_mount_to_flow(
            spec, mountpoint, fstype, evidence=f"mount: {raw.strip()}"
        )
        if flow is not None:
            key = (spec, mountpoint)
            if key not in seen:
                seen.add(key)
                flows.append(flow)

    return flows


# ---------------------------------------------------------------------------
# Established TCP connections -> DataFlow
# ---------------------------------------------------------------------------
def parse_tcp_connections_ss(text: str) -> List[DataFlow]:
    """Parse established outbound TCP connections from ``ss -tnp``.

    Each established connection becomes a :class:`DataFlow` with mechanism
    :data:`FlowMechanism.TCP_DEPENDENCY` pointing at the peer.  Loopback peers
    are skipped; duplicate peers ``(host, port)`` are collapsed.
    """
    flows: List[DataFlow] = []
    seen = set()
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("State") or stripped.startswith("Netid"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        # Layout: State Recv-Q Send-Q Local Peer [Process].
        state = parts[0]
        if state.upper() not in ("ESTAB", "ESTABLISHED"):
            continue
        peer_ap = _split_addr_port(parts[4])
        if peer_ap is None:
            continue
        peer_host, peer_port = peer_ap
        if peer_host in ("127.0.0.1", "::1") or peer_host.startswith("127."):
            continue
        proc = _parse_ss_process(parts[5] if len(parts) > 5 else "")
        key = (peer_host, peer_port)
        if key in seen:
            continue
        seen.add(key)
        flows.append(
            DataFlow(
                mechanism=FlowMechanism.TCP_DEPENDENCY,
                direction="outbound",
                peer=Endpoint(address=peer_host, port=peer_port, label=proc),
                detail=f"established TCP to {peer_host}:{peer_port}",
                confidence=ConfidenceLevel.OBSERVED,
                evidence=[f"ss: {line.strip()}"],
            )
        )
    return flows


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
# (substring) -> (product-name, category)
_SERVICE_HINTS = [
    ("nginx", ("nginx", "webserver")),
    ("apache2", ("apache", "webserver")),
    ("httpd", ("apache", "webserver")),
    ("caddy", ("caddy", "webserver")),
    ("postgresql", ("postgresql", "database")),
    ("postgres", ("postgresql", "database")),
    ("mariadb", ("mariadb", "database")),
    ("mysql", ("mysql", "database")),
    ("mongod", ("mongodb", "database")),
    ("redis", ("redis", "cache")),
    ("memcached", ("memcached", "cache")),
    ("kafka", ("kafka", "queue")),
    ("rabbitmq", ("rabbitmq", "queue")),
    ("elasticsearch", ("elasticsearch", "search")),
    ("docker", ("docker", "container-runtime")),
    ("containerd", ("containerd", "container-runtime")),
    ("sshd", ("openssh", "remote-access")),
]

# Well-known listening ports -> (product-name, category)
_PORT_HINTS = {
    80: ("http", "webserver"),
    443: ("https", "webserver"),
    5432: ("postgresql", "database"),
    3306: ("mysql", "database"),
    27017: ("mongodb", "database"),
    6379: ("redis", "cache"),
    11211: ("memcached", "cache"),
    9092: ("kafka", "queue"),
    5672: ("rabbitmq", "queue"),
    9200: ("elasticsearch", "search"),
    22: ("openssh", "remote-access"),
}


def fingerprint(software: SoftwareInventory) -> List[AppFingerprint]:
    """Derive higher-level :class:`AppFingerprint` guesses from inventory.

    Combines evidence from services, listeners, and containers.  One
    fingerprint per product name, aggregating evidence strings.
    """
    found: dict = {}  # product-name -> AppFingerprint

    def _add(product: str, category: str, evidence: str) -> None:
        fp = found.get(product)
        if fp is None:
            fp = AppFingerprint(
                name=product,
                category=category,
                confidence=ConfidenceLevel.INFERRED,
            )
            found[product] = fp
        if evidence not in fp.evidence:
            fp.evidence.append(evidence)

    # Services.
    for svc in software.services:
        name = (svc.name or "").lower()
        for needle, (product, category) in _SERVICE_HINTS:
            if needle in name:
                _add(product, category, f"service:{svc.name}")
                break

    # Listeners (by process name and by well-known port).
    for ln in software.listeners:
        pname = (ln.process or "").lower()
        matched = False
        for needle, (product, category) in _SERVICE_HINTS:
            if pname and needle in pname:
                _add(product, category, f"listener:{pname}:{ln.port}")
                matched = True
                break
        if not matched and ln.port in _PORT_HINTS:
            product, category = _PORT_HINTS[ln.port]
            _add(product, category, f"port:{ln.port}")

    # Containers (by image name).
    for c in software.containers:
        image = (c.image or "").lower()
        for needle, (product, category) in _SERVICE_HINTS:
            if needle in image:
                _add(product, category, f"container:{c.image}")
                break

    return list(found.values())
