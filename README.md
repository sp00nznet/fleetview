# FleetView

**A holistic, point-in-time picture of an entire environment.** FleetView connects to
vCenter/ESXi, Proxmox, AWS, and GCP, introspects every VM / container / instance, and builds a
single, provider-agnostic model of the whole fleet — what each box *is*, what it's *running*,
and what data is *shuttled between* boxes. From that model it can reproduce a box's full
configuration (IaC) and analyze it for improvements and **cross-platform cost efficiency**.

> **Not a live-metrics tool.** This is deliberately *not* Datadog. FleetView captures
> **structure and configuration** — snapshots of the stack — not minute-by-minute telemetry.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Status — Milestone 1

| Capability | State |
|---|---|
| Unified data model (`Fleet` / `Node` / flows / analysis) | ✅ done |
| VMware / ESXi collector (pyVmomi, read-only) | ✅ done |
| JSON snapshot store (+ free diffing) | ✅ done |
| CLI (`scan` / `show` / `list` / `schema`) | ✅ done |
| JSON Schema export (→ frontend TS types) | ✅ done |
| Reproduce (IaC) + Analyze (cost) engines | �stub — interfaces defined |
| Proxmox / AWS / GCP collectors | ⬜ M2 |
| React/TS holistic frontend | ⬜ M4 (stub in `frontend/`) |

## Requirements

- **Python 3.11+** (not currently installed on this machine — install before running)
- For the VMware collector: `pip install 'fleetview[vmware]'` (pulls in pyVmomi)
- Node 20+ only needed later, for the frontend

## Install

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e '.[vmware,dev]'
```

## Usage

```bash
# what can I collect from?
fleetview providers

# scan a vCenter or standalone ESXi host (read-only)
fleetview scan vmware --host vcenter.example.com --username svc_fleetview --password '***' --insecure

# ...or via environment variables
export FLEETVIEW_VMWARE_HOST=vcenter.example.com
export FLEETVIEW_VMWARE_USER=svc_fleetview
export FLEETVIEW_VMWARE_PASSWORD='***'
fleetview scan vmware --insecure

# list and inspect snapshots
fleetview list
fleetview show vmware-20260529T120000Z -v

# export the data-model schema for the frontend
fleetview schema export --out schema/fleet.schema.json
```

A scan writes an immutable JSON snapshot under `snapshots/`. Because snapshots are timestamped
and stable-keyed, comparing two of them gives you environment **diffing** for free.

> ⚠️ Snapshots can contain sensitive inventory (IPs, hostnames, annotations). `snapshots/` is
> git-ignored by default.

## Layout

```
fleetview/
  models/        # unified data model — the contract everything pivots on
  collectors/    # provider adapters (vmware done; proxmox/aws/gcp next)
  reproduce/     # IaC generation (interface defined, M3)
  analyze/       # findings + cross-platform cost (interface defined, M3)
  store.py       # snapshot persistence
  schema.py      # JSON Schema export
  cli.py         # entrypoint
docs/            # architecture
frontend/        # holistic view (React/TS, M4)
```

## Heritage

FleetView consolidates two earlier projects:
- **whatdoesthisboxdo** — per-box introspection → feeds `collectors` + `reproduce`.
- **opsview** — operational viewpoint/UX → feeds the `frontend`.
