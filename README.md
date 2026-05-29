# FleetView

**A holistic, point-in-time picture of an entire environment.** FleetView connects to
vCenter/ESXi, Proxmox, AWS, and GCP, introspects every VM / container / instance, and builds a
single, provider-agnostic model of the whole fleet — what each box *is*, what it's *running*,
and what data is *shuttled between* boxes. From that model it can reproduce a box's full
configuration (IaC) and analyze it for improvements and **cross-platform cost efficiency**.

> **Not a live-metrics tool.** This is deliberately *not* Datadog. FleetView captures
> **structure and configuration** — snapshots of the stack — not minute-by-minute telemetry.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design and
[`docs/HERITAGE.md`](docs/HERITAGE.md) for how it consolidates the earlier `whatdoesthisboxdo`
and `opsview` projects.

## Status

| Capability | State |
|---|---|
| Unified data model (`Fleet` / `Node` / flows / analysis) | ✅ M1 |
| JSON snapshot store (+ free diffing) | ✅ M1 |
| CLI (`scan`/`show`/`list`/`analyze`/`reproduce`/`inspect`/`schema`) | ✅ |
| JSON Schema export (→ frontend TS types) | ✅ M1 |
| Collectors: VMware/ESXi, Proxmox, AWS, GCP (read-only) | ✅ M2 |
| Analyze: cross-platform cost, rightsizing, EOL, hygiene, fleet-graph | ✅ M3 |
| Reproduce: Terraform (AWS + vSphere), Ansible | ✅ M3 |
| React/TS holistic frontend (overview, nodes, flow graph, recommendations) | ✅ M4 |
| Deep inspection over SSH (packages/services/ports/containers/flows) | ✅ M5 |

All collectors and the SSH inspector use **lazy SDK imports** — install only the extras you
need. 46 tests pass; cloud/hypervisor/SSH paths are covered with mocked SDK responses (real
targets need live credentials).

## Requirements

- **Python 3.11+**
- Provider SDKs are optional extras — install per provider:
  `pip install 'fleetview[vmware]'` · `[proxmox]` · `[aws]` · `[gcp]` · `[ssh]` · or `[all]`
- **Node 20+** for the frontend

## Install

```bash
python -m venv .venv
. .venv/Scripts/activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -e '.[all,dev]'         # or pick specific extras
```

## Usage

```bash
# what can I collect from?
fleetview providers

# scan providers (read-only). Flags or FLEETVIEW_<PROVIDER>_* env vars.
fleetview scan vmware  --host vcenter.example.com --username svc --password '***' --insecure
fleetview scan proxmox --host pve.example.com --token-id 'root@pam!fv' --token-secret '***'
fleetview scan aws     --region us-east-1 --profile prod
fleetview scan gcp     --project my-project

# list and inspect snapshots
fleetview list
fleetview show <snapshot> -v

# analyze: cross-platform cost + findings (re-saves snapshot with analysis attached)
fleetview analyze <snapshot>

# generate IaC to recreate a node — ideally on a different platform
fleetview reproduce <snapshot> --node "aws:123456789012:web01" --target terraform-aws --out ./out
fleetview reproduce <snapshot> --node "<id>" --target ansible --out ./out

# deep-inspect a node over SSH (needs [ssh]) to fill software inventory + data flows
fleetview inspect <snapshot> --node "<id>" --username ubuntu --key ~/.ssh/id_rsa --sudo

# export the data-model schema (feeds the frontend's TS types)
fleetview schema export --out schema/fleet.schema.json
```

A scan writes an immutable JSON snapshot under `snapshots/`. Because snapshots are timestamped
and stable-keyed, comparing two gives you environment **diffing** for free.

> ⚠️ Snapshots can contain sensitive inventory (IPs, hostnames, annotations). `snapshots/` is
> git-ignored by default.

## Frontend (holistic view)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 — loads frontend/public/sample-fleet.json
```

Four views: **Overview** (fleet totals + cost roll-up), **Nodes** (table + per-node
drilldown), **Flow graph** (the data-flow graph between boxes), and **Recommendations**
(findings ranked by savings). A file-upload control loads any snapshot exported by the CLI.

## Layout

```
fleetview/
  models/        # unified data model — the contract everything pivots on
  collectors/    # provider adapters: vmware, proxmox, aws, gcp (lazy SDK imports)
  inspect/       # SSH deep inspection: probes -> software inventory + data flows
  analyze/       # findings + cross-platform cost (pricing tables + graph analyzers)
  reproduce/     # IaC generation: terraform (aws/vsphere), ansible
  store.py       # immutable JSON snapshots
  schema.py      # JSON Schema export
  cli.py         # entrypoint
docs/            # ARCHITECTURE.md, HERITAGE.md
frontend/        # React/TS holistic view (Vite)
tools/           # make_sample.py — generate a demo fleet snapshot
```

## Heritage

FleetView consolidates two earlier projects (see `docs/HERITAGE.md`):
- **whatdoesthisboxdo** — per-box introspection, cost tables, IaC generators → `analyze` + `reproduce`.
- **opsview** — vCenter/Proxmox enumeration, SSH probes, topology/flow analysis → `collectors` + `inspect` + frontend.
