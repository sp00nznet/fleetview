"""FleetView CLI.

    fleetview providers                  # list available collectors
    fleetview scan vmware --host ... ... # collect a snapshot
    fleetview show <snapshot-id|path>    # summarize a stored snapshot
    fleetview list                       # list stored snapshots
    fleetview schema export              # write the Fleet JSON Schema

Credentials may be passed as flags or environment variables (flags win). For VMware:
    FLEETVIEW_VMWARE_HOST / _USER / _PASSWORD / _PORT
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import schema as schema_mod
from .collectors import available_providers, load_collector_class
from .collectors.base import CollectorError
from .models import Fleet, FleetMeta
from .store import SnapshotStore


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _build_collector(provider: str, args: argparse.Namespace):
    cls = load_collector_class(provider)
    if provider == "vmware":
        host = args.host or _env("FLEETVIEW_VMWARE_HOST")
        user = args.username or _env("FLEETVIEW_VMWARE_USER")
        password = args.password or _env("FLEETVIEW_VMWARE_PASSWORD")
        port = int(args.port or _env("FLEETVIEW_VMWARE_PORT") or 443)
        if not (host and user and password):
            raise CollectorError(
                "vmware requires --host, --username, --password "
                "(or FLEETVIEW_VMWARE_HOST/_USER/_PASSWORD)"
            )
        return cls(
            host=host,
            username=user,
            password=password,
            port=port,
            verify_ssl=not args.insecure,
        )
    raise CollectorError(f"No CLI wiring for provider '{provider}' yet")


def cmd_providers(_args) -> int:
    print("Available providers:")
    for p in available_providers():
        print(f"  - {p}")
    return 0


def cmd_scan(args) -> int:
    collector = _build_collector(args.provider, args)
    print(f"Connecting to {args.provider} ...", file=sys.stderr)
    if not collector.test_connection():
        print("Connection test failed.", file=sys.stderr)
        return 2
    print("Collecting inventory ...", file=sys.stderr)
    result = collector.collect()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = args.id or f"{args.provider}-{stamp}"
    fleet = Fleet(
        meta=FleetMeta(
            id=snapshot_id,
            scope=args.scope or f"{args.provider}:{getattr(collector, 'host', '')}",
            warnings=result.warnings,
        ),
        providers=[result.provider],
        nodes=result.nodes,
    )

    store = SnapshotStore(args.store)
    path = store.save(fleet)
    print(f"Saved snapshot '{snapshot_id}' ({len(fleet.nodes)} nodes) -> {path}")
    for w in result.warnings:
        print(f"  warning: {w}", file=sys.stderr)
    _print_summary(fleet)
    return 0


def cmd_list(args) -> int:
    store = SnapshotStore(args.store)
    snaps = store.list_snapshots()
    if not snaps:
        print(f"No snapshots in {args.store}/")
        return 0
    for s in snaps:
        print(s)
    return 0


def cmd_show(args) -> int:
    store = SnapshotStore(args.store)
    if os.path.exists(args.snapshot):
        fleet = store.load_path(args.snapshot)
    else:
        fleet = store.load(args.snapshot)
    _print_summary(fleet, verbose=args.verbose)
    return 0


def cmd_schema(args) -> int:
    path = schema_mod.export(args.out)
    print(f"Wrote Fleet JSON Schema -> {path}")
    return 0


def _print_summary(fleet: Fleet, verbose: bool = False) -> None:
    print()
    print(f"Fleet snapshot: {fleet.meta.id}")
    print(f"  captured_at : {fleet.meta.captured_at.isoformat()}")
    print(f"  scope       : {fleet.meta.scope}")
    print(f"  providers   : {', '.join(p.kind.value for p in fleet.providers)}")
    print(f"  nodes       : {len(fleet.nodes)}")
    print(f"  total vCPUs : {fleet.total_vcpus}")
    print(f"  total RAM   : {fleet.total_memory_gb} GB")
    print(f"  total disk  : {fleet.total_storage_gb} GB")
    if verbose:
        print()
        for n in fleet.nodes:
            ip = n.primary_ip or "-"
            print(
                f"  - {n.name:<32} {n.power_state.value:<9} "
                f"{n.compute.vcpus or '?'}cpu/{n.compute.memory_mb or '?'}MB  "
                f"{n.os.distro or n.os.family.value}  {ip}"
            )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fleetview", description="Holistic environment inventory.")
    p.add_argument("--store", default="snapshots", help="snapshot directory (default: snapshots)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="list available collectors").set_defaults(func=cmd_providers)

    scan = sub.add_parser("scan", help="collect a snapshot from a provider")
    scan.add_argument("provider", choices=available_providers())
    scan.add_argument("--host")
    scan.add_argument("--username")
    scan.add_argument("--password")
    scan.add_argument("--port")
    scan.add_argument("--insecure", action="store_true", help="skip TLS verification")
    scan.add_argument("--id", help="snapshot id (default: <provider>-<timestamp>)")
    scan.add_argument("--scope", help="human label for what was scanned")
    scan.set_defaults(func=cmd_scan)

    lst = sub.add_parser("list", help="list stored snapshots")
    lst.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="summarize a stored snapshot")
    show.add_argument("snapshot", help="snapshot id or path to a .json file")
    show.add_argument("-v", "--verbose", action="store_true", help="list every node")
    show.set_defaults(func=cmd_show)

    sch = sub.add_parser("schema", help="schema utilities")
    sch_sub = sch.add_subparsers(dest="schema_command", required=True)
    exp = sch_sub.add_parser("export", help="write the Fleet JSON Schema")
    exp.add_argument("--out", default="schema/fleet.schema.json")
    exp.set_defaults(func=cmd_schema)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
