"""FleetView CLI.

    fleetview providers                          # list available collectors
    fleetview scan <provider> ...                # collect a snapshot (vmware/proxmox/aws/gcp)
    fleetview show <snapshot-id|path> [-v]       # summarize a stored snapshot
    fleetview list                               # list stored snapshots
    fleetview analyze <snapshot>                 # attach findings + cross-platform cost
    fleetview reproduce <snapshot> --node <id> --target terraform-aws --out <dir>
    fleetview inspect <snapshot> --node <id> --username U (--key K | --password P)
    fleetview schema export                      # write the Fleet JSON Schema

Credentials may be passed as flags or environment variables (flags win). Env var prefixes:
    FLEETVIEW_VMWARE_* / _PROXMOX_* / _AWS_* / _GCP_*
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


def _load(store: SnapshotStore, ref: str) -> Fleet:
    return store.load_path(ref) if os.path.exists(ref) else store.load(ref)


# ----------------------------------------------------------------- collectors


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
        return cls(host=host, username=user, password=password, port=port,
                   verify_ssl=not args.insecure)

    if provider == "proxmox":
        host = args.host or _env("FLEETVIEW_PROXMOX_HOST")
        token_id = args.token_id or _env("FLEETVIEW_PROXMOX_TOKEN_ID")
        token_secret = args.token_secret or _env("FLEETVIEW_PROXMOX_TOKEN_SECRET")
        user = args.username or _env("FLEETVIEW_PROXMOX_USER")
        password = args.password or _env("FLEETVIEW_PROXMOX_PASSWORD")
        port = int(args.port or _env("FLEETVIEW_PROXMOX_PORT") or 8006)
        if not host or not ((token_id and token_secret) or (user and password)):
            raise CollectorError(
                "proxmox requires --host and either --token-id/--token-secret or "
                "--username/--password (or the matching FLEETVIEW_PROXMOX_* env vars)"
            )
        return cls(host=host, token_id=token_id, token_secret=token_secret, username=user,
                   password=password, port=port, verify_ssl=not args.insecure)

    if provider == "aws":
        region = args.region or _env("FLEETVIEW_AWS_REGION")
        if not region:
            raise CollectorError(
                "aws requires --region (or FLEETVIEW_AWS_REGION). Credentials come from "
                "--profile/--access-key/--secret-key, FLEETVIEW_AWS_* env vars, or the default "
                "boto3 chain."
            )
        return cls(region=region,
                   profile=args.profile or _env("FLEETVIEW_AWS_PROFILE"),
                   access_key=args.access_key or _env("FLEETVIEW_AWS_ACCESS_KEY"),
                   secret_key=args.secret_key or _env("FLEETVIEW_AWS_SECRET_KEY"))

    if provider == "gcp":
        project = args.project or _env("FLEETVIEW_GCP_PROJECT")
        zones_raw = args.zones or _env("FLEETVIEW_GCP_ZONES")
        zones = [z.strip() for z in zones_raw.split(",") if z.strip()] if zones_raw else None
        if not project:
            raise CollectorError(
                "gcp requires --project (or FLEETVIEW_GCP_PROJECT). Auth uses Application "
                "Default Credentials (GOOGLE_APPLICATION_CREDENTIALS)."
            )
        return cls(project=project, zones=zones)

    raise CollectorError(f"No CLI wiring for provider '{provider}'")


# ----------------------------------------------------------------- commands


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
            scope=args.scope or f"{args.provider}:{result.provider.instance}",
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
    _print_summary(_load(store, args.snapshot), verbose=args.verbose)
    return 0


def cmd_analyze(args) -> int:
    from .analyze import analyze_fleet, total_estimated_savings

    store = SnapshotStore(args.store)
    fleet = _load(store, args.snapshot)
    analyze_fleet(fleet)
    store.save(fleet)

    findings = [
        (n, f) for n in fleet.nodes if n.analysis for f in n.analysis.findings
    ]
    findings.sort(key=lambda nf: (nf[1].estimated_monthly_savings_usd or 0), reverse=True)
    print(f"Analyzed {len(fleet.nodes)} nodes - {len(findings)} findings")
    print(f"Estimated total monthly savings: ${total_estimated_savings(fleet)}\n")
    for node, f in findings[: args.top]:
        save = f" (~${f.estimated_monthly_savings_usd}/mo)" if f.estimated_monthly_savings_usd else ""
        print(f"  [{f.severity.value:<8}] {node.name}: {f.title}{save}")
        if f.recommendation:
            print(f"             -> {f.recommendation}")
    if len(findings) > args.top:
        print(f"  ... and {len(findings) - args.top} more (snapshot re-saved with full analysis)")
    return 0


def cmd_reproduce(args) -> int:
    from pathlib import Path

    from .reproduce import available_targets, get_reproducer

    store = SnapshotStore(args.store)
    fleet = _load(store, args.snapshot)
    node = fleet.node_index().get(args.node)
    if node is None:
        print(f"error: node '{args.node}' not found. Try 'fleetview show {args.snapshot} -v'.",
              file=sys.stderr)
        return 2
    try:
        reproducer = get_reproducer(args.target)
    except ValueError as exc:
        print(f"error: {exc} (targets: {', '.join(available_targets())})", file=sys.stderr)
        return 2

    artifacts = reproducer.reproduce(node)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for art in artifacts:
        dest = out / art.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(art.content, encoding="utf-8")
        print(f"  wrote {dest}")
    print(f"Generated {len(artifacts)} {args.target} artifact(s) for '{node.name}' -> {out}/")
    return 0


def cmd_inspect(args) -> int:
    from .inspect import enrich_node  # lazy: keeps paramiko optional

    store = SnapshotStore(args.store)
    fleet = _load(store, args.snapshot)
    node = fleet.node_index().get(args.node)
    if node is None:
        print(f"error: node '{args.node}' not found in snapshot", file=sys.stderr)
        return 2
    if not (args.key or args.password):
        print("error: provide --key or --password", file=sys.stderr)
        return 2

    print(f"Deep-inspecting {node.id} ({node.primary_ip or args.host or '?'}) ...", file=sys.stderr)
    try:
        enrich_node(
            node,
            host=args.host,
            username=args.username,
            key_path=args.key,
            password=args.password,
            port=int(args.port or 22),
            sudo=args.sudo,
            capture_config_contents=args.capture_configs,
        )
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # connection / auth / host errors
        print(f"error: inspection failed: {exc}", file=sys.stderr)
        return 2

    store.save(fleet)
    inv = node.software
    print(f"\nDeep inspection of {node.name} ({node.id}):")
    print(f"  packages    : {len(inv.packages)}")
    print(f"  services    : {len(inv.services)}")
    print(f"  processes   : {len(inv.processes)}")
    print(f"  listeners   : {len(inv.listeners)}")
    print(f"  containers  : {len(inv.containers)}")
    print(f"  config files: {len(inv.config_files)}")
    print(f"  flows       : {len(node.flows)}")
    if inv.fingerprints:
        print(f"  fingerprints: {', '.join(sorted(fp.name for fp in inv.fingerprints))}")
    return 0


def cmd_schema(args) -> int:
    path = schema_mod.export(args.out)
    print(f"Wrote Fleet JSON Schema -> {path}")
    return 0


# ----------------------------------------------------------------- output


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
                f"{n.os.distro or n.os.family.value}  {ip}  [{n.id}]"
            )


# ----------------------------------------------------------------- parser


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
    # proxmox
    scan.add_argument("--token-id", help="Proxmox API token id (user@realm!tokenid)")
    scan.add_argument("--token-secret", help="Proxmox API token secret")
    # aws
    scan.add_argument("--region", help="AWS region")
    scan.add_argument("--profile", help="AWS named profile")
    scan.add_argument("--access-key", help="AWS access key id")
    scan.add_argument("--secret-key", help="AWS secret access key")
    # gcp
    scan.add_argument("--project", help="GCP project id")
    scan.add_argument("--zones", help="GCP comma-separated zones (default: all)")
    # common
    scan.add_argument("--id", help="snapshot id (default: <provider>-<timestamp>)")
    scan.add_argument("--scope", help="human label for what was scanned")
    scan.set_defaults(func=cmd_scan)

    sub.add_parser("list", help="list stored snapshots").set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="summarize a stored snapshot")
    show.add_argument("snapshot", help="snapshot id or path to a .json file")
    show.add_argument("-v", "--verbose", action="store_true", help="list every node")
    show.set_defaults(func=cmd_show)

    an = sub.add_parser("analyze", help="attach findings + cross-platform cost to a snapshot")
    an.add_argument("snapshot", help="snapshot id or path")
    an.add_argument("--top", type=int, default=20, help="how many findings to print")
    an.set_defaults(func=cmd_analyze)

    rep = sub.add_parser("reproduce", help="generate IaC to recreate a node")
    rep.add_argument("snapshot", help="snapshot id or path")
    rep.add_argument("--node", required=True, help="Node.id to reproduce")
    rep.add_argument("--target", default="terraform-aws",
                     help="terraform-aws | terraform-vsphere | ansible")
    rep.add_argument("--out", default="reproduce-out", help="output directory")
    rep.set_defaults(func=cmd_reproduce)

    insp = sub.add_parser("inspect", help="deep-inspect a node in a snapshot over SSH")
    insp.add_argument("snapshot", help="snapshot id or path")
    insp.add_argument("--node", required=True, help="Node.id to inspect")
    insp.add_argument("--username", required=True, help="SSH username")
    insp.add_argument("--host", help="SSH host (defaults to the node's primary_ip)")
    insp.add_argument("--port", help="SSH port (default 22)")
    insp.add_argument("--key", help="path to SSH private key")
    insp.add_argument("--password", help="SSH password")
    insp.add_argument("--sudo", action="store_true", help="run probe commands via sudo -n")
    insp.add_argument("--capture-configs", action="store_true",
                      help="capture full config-file contents (not just metadata)")
    insp.set_defaults(func=cmd_inspect)

    sch = sub.add_parser("schema", help="schema utilities")
    sch_sub = sch.add_subparsers(dest="schema_command", required=True)
    exp = sch_sub.add_parser("export", help="write the Fleet JSON Schema")
    exp.add_argument("--out", default="schema/fleet.schema.json")
    exp.set_defaults(func=cmd_schema)

    return p


def main(argv: list[str] | None = None) -> int:
    # Snapshot data (node names, OS strings) may contain non-ASCII; the Windows console
    # defaults to cp1252. Prefer UTF-8 so printing never crashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
