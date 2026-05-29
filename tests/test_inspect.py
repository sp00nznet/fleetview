"""Unit tests for FleetView deep-inspection parsers.

These exercise the pure parse_* functions in ``fleetview.inspect.probes`` with
realistic captured command output.  No SSH / paramiko required.
"""

from __future__ import annotations

from fleetview.inspect import probes
from fleetview.models.enums import FlowMechanism
from fleetview.models.software import SoftwareInventory


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
DPKG = """\
Desired=Unknown/Install/Remove/Purge/Hold
| Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
|/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
||/ Name           Version          Architecture Description
+++-==============-================-============-=================================
ii  nginx          1.18.0-6ubuntu14 amd64        small, powerful, scalable web/proxy server
ii  libc6:amd64    2.31-0ubuntu9.9  amd64        GNU C Library: Shared libraries
rc  oldpkg         1.0              amd64        removed but config remains
ii  postgresql-14  14.5-1.pgdg22    amd64        object-relational SQL database
"""


def test_parse_packages_dpkg():
    pkgs = probes.parse_packages_dpkg(DPKG)
    names = {p.name for p in pkgs}
    assert names == {"nginx", "libc6", "postgresql-14"}  # rc line excluded
    nginx = next(p for p in pkgs if p.name == "nginx")
    assert nginx.version == "1.18.0-6ubuntu14"
    assert nginx.manager == "apt"
    # ":amd64" suffix stripped from name.
    assert any(p.name == "libc6" for p in pkgs)


RPM = "nginx\t1.20.1-14.el9\nopenssh-server\t8.7p1-34.el9\n"


def test_parse_packages_rpm_tabbed():
    pkgs = probes.parse_packages_rpm(RPM)
    assert len(pkgs) == 2
    p = pkgs[0]
    assert p.name == "nginx"
    assert p.version == "1.20.1-14.el9"
    assert p.manager == "yum"


def test_parse_packages_rpm_plain():
    pkgs = probes.parse_packages_rpm("nginx-1.20.1-14.el9.x86_64\n")
    assert len(pkgs) == 1
    assert pkgs[0].name == "nginx"
    assert pkgs[0].version == "1.20.1-14.el9"


PIP = """\
Package    Version
---------- -------
Flask      2.2.5
gunicorn   20.1.0
"""


def test_parse_packages_pip():
    pkgs = probes.parse_packages_pip(PIP)
    assert {(p.name, p.version) for p in pkgs} == {
        ("Flask", "2.2.5"),
        ("gunicorn", "20.1.0"),
    }
    assert all(p.manager == "pip" for p in pkgs)


def test_parse_packages_pip_freeze():
    pkgs = probes.parse_packages_pip("requests==2.31.0\nurllib3==2.0.4\n")
    assert {(p.name, p.version) for p in pkgs} == {
        ("requests", "2.31.0"),
        ("urllib3", "2.0.4"),
    }


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
SYSTEMCTL = """\
  ssh.service            loaded active   running OpenBSD Secure Shell server
  nginx.service          loaded active   running A high performance web server
● postgresql.service     loaded failed   failed  PostgreSQL RDBMS
  cron.service           loaded active   running Regular background program processing daemon
  systemd-journald.service loaded active running Journal Service
"""


def test_parse_services_systemctl():
    svcs = probes.parse_services_systemctl(SYSTEMCTL)
    by_name = {s.name: s for s in svcs}
    assert "nginx" in by_name
    assert by_name["nginx"].state == "running"
    assert by_name["nginx"].description == "A high performance web server"
    # Bullet stripped, failed sub-state captured.
    assert by_name["postgresql"].state == "failed"
    assert "ssh" in by_name


# ---------------------------------------------------------------------------
# Listeners
# ---------------------------------------------------------------------------
SS_LISTEN = """\
State    Recv-Q   Send-Q     Local Address:Port      Peer Address:Port   Process
LISTEN   0        511              0.0.0.0:80             0.0.0.0:*       users:(("nginx",pid=1234,fd=6))
LISTEN   0        4096           127.0.0.1:5432           0.0.0.0:*       users:(("postgres",pid=900,fd=5))
LISTEN   0        128                 [::]:22                [::]:*       users:(("sshd",pid=700,fd=3))
LISTEN   0        511                 [::]:80                [::]:*       users:(("nginx",pid=1234,fd=7))
"""


def test_parse_listeners_ss():
    listeners = probes.parse_listeners_ss(SS_LISTEN)
    assert len(listeners) == 4
    first = listeners[0]
    assert first.protocol == "tcp"
    assert first.address == "0.0.0.0"
    assert first.port == 80
    assert first.process == "nginx"
    # IPv6 bracket form parsed.
    sshd = next(l for l in listeners if l.port == 22)
    assert sshd.address == "::"
    assert sshd.process == "sshd"
    pg = next(l for l in listeners if l.port == 5432)
    assert pg.address == "127.0.0.1"
    assert pg.process == "postgres"


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
PS = """\
USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root         1  0.0  0.1 168940 11800 ?        Ss   May01   0:12 /sbin/init
www-data  1234  2.5  1.3 145600 54200 ?        S    10:00   0:30 nginx: worker process
postgres   900  0.1  3.0 400000 120000 ?       Ss   May01   1:05 /usr/lib/postgresql/14/bin/postgres
"""


def test_parse_processes_ps():
    procs = probes.parse_processes_ps(PS)
    assert len(procs) == 3
    nginx = next(p for p in procs if p.pid == 1234)
    assert nginx.user == "www-data"
    assert nginx.cmdline == "nginx: worker process"
    assert nginx.name == "nginx"
    init = next(p for p in procs if p.pid == 1)
    assert init.cmdline == "/sbin/init"
    assert init.name == "init"


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
DOCKER = (
    '{"ID":"abc123","Image":"nginx:latest","Names":"web",'
    '"Status":"Up 3 hours","Ports":"0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp"}\n'
    '{"ID":"def456","Image":"redis:7","Names":"cache",'
    '"Status":"Up 2 days","Ports":"6379/tcp"}\n'
)


def test_parse_docker_ps():
    containers = probes.parse_docker_ps(DOCKER)
    assert len(containers) == 2
    web = containers[0]
    assert web.id == "abc123"
    assert web.image == "nginx:latest"
    assert web.name == "web"
    assert web.runtime == "docker"
    assert web.state == "Up 3 hours"
    # Ports parsed into typed ListeningPort objects.
    web_ports = {(p.port, p.protocol) for p in web.ports}
    assert web_ports == {(80, "tcp"), (443, "tcp")}
    assert web.ports[0].address == "0.0.0.0"
    cache = containers[1]
    assert cache.image == "redis:7"
    assert [p.port for p in cache.ports] == [6379]


def test_parse_docker_ps_skips_garbage():
    assert probes.parse_docker_ps("not json\n\n") == []


# ---------------------------------------------------------------------------
# Mounts -> DataFlow
# ---------------------------------------------------------------------------
FSTAB = """\
# /etc/fstab
UUID=1111-2222 /            ext4   defaults        0 1
nfs01.example.com:/exports/data  /mnt/data  nfs  defaults,_netdev  0 0
//fileserver/share  /mnt/share  cifs  credentials=/etc/smb.cred  0 0
tmpfs  /run  tmpfs  defaults  0 0
"""

MOUNT = """\
sysfs on /sys type sysfs (rw,nosuid,nodev,noexec,relatime)
nfs01.example.com:/exports/data on /mnt/data type nfs4 (rw,relatime,vers=4.2)
/dev/sda1 on / type ext4 (rw,relatime)
"""


def test_parse_mounts_nfs_and_cifs():
    flows = probes.parse_mounts(FSTAB, MOUNT)
    mechs = {f.mechanism for f in flows}
    assert FlowMechanism.NFS_MOUNT in mechs
    assert FlowMechanism.SMB_SHARE in mechs

    nfs = next(f for f in flows if f.mechanism is FlowMechanism.NFS_MOUNT)
    assert nfs.peer.address == "nfs01.example.com"
    assert nfs.peer.label == "nfs01.example.com:/exports/data"
    assert "/mnt/data" in nfs.detail
    assert nfs.direction == "bidirectional"
    assert nfs.evidence  # fstab/mount line captured

    cifs = next(f for f in flows if f.mechanism is FlowMechanism.SMB_SHARE)
    assert cifs.peer.address == "fileserver"
    assert "share" in cifs.detail

    # fstab + mount both list the NFS export at the same mountpoint -> deduped.
    nfs_flows = [f for f in flows if f.mechanism is FlowMechanism.NFS_MOUNT]
    assert len(nfs_flows) == 1


def test_parse_mounts_ignores_local_fs():
    flows = probes.parse_mounts("UUID=x / ext4 defaults 0 1\n", "")
    assert flows == []


# ---------------------------------------------------------------------------
# Established connections -> DataFlow
# ---------------------------------------------------------------------------
SS_CONN = """\
State  Recv-Q  Send-Q   Local Address:Port      Peer Address:Port   Process
ESTAB  0       0          10.0.0.5:54321        10.0.0.20:5432       users:(("python3",pid=2001,fd=9))
ESTAB  0       0          10.0.0.5:33210         10.0.0.9:6379       users:(("python3",pid=2001,fd=10))
ESTAB  0       0         127.0.0.1:44002        127.0.0.1:8000       users:(("curl",pid=3003,fd=3))
ESTAB  0       0          10.0.0.5:48800        10.0.0.20:5432       users:(("python3",pid=2055,fd=4))
"""


def test_parse_tcp_connections_ss():
    flows = probes.parse_tcp_connections_ss(SS_CONN)
    # loopback peer skipped; duplicate peer (10.0.0.20:5432) collapsed.
    peers = {(f.peer.address, f.peer.port) for f in flows}
    assert peers == {("10.0.0.20", 5432), ("10.0.0.9", 6379)}
    assert all(f.mechanism is FlowMechanism.TCP_DEPENDENCY for f in flows)
    assert all(f.direction == "outbound" for f in flows)
    pg = next(f for f in flows if f.peer.port == 5432)
    assert pg.peer.label == "python3"
    assert pg.evidence


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
def test_fingerprint_from_services_and_listeners():
    inv = SoftwareInventory()
    inv.services = probes.parse_services_systemctl(SYSTEMCTL)
    inv.listeners = probes.parse_listeners_ss(SS_LISTEN)
    inv.containers = probes.parse_docker_ps(DOCKER)

    fps = probes.fingerprint(inv)
    by_name = {fp.name: fp for fp in fps}
    assert "nginx" in by_name
    assert by_name["nginx"].category == "webserver"
    assert "postgresql" in by_name
    assert by_name["postgresql"].category == "database"
    assert "openssh" in by_name
    # redis container -> cache fingerprint.
    assert "redis" in by_name
    assert by_name["redis"].category == "cache"
    assert by_name["nginx"].evidence  # has at least one piece of evidence


def test_fingerprint_by_well_known_port():
    inv = SoftwareInventory()
    # A listener on 3306 with no process name -> mysql via port hint.
    inv.listeners = probes.parse_listeners_ss(
        "State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
        "LISTEN 0 80 0.0.0.0:3306 0.0.0.0:*\n"
    )
    fps = probes.fingerprint(inv)
    assert "mysql" in {fp.name for fp in fps}
