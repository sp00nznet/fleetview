# FleetView — Architecture

FleetView builds a **holistic, point-in-time picture of an entire environment** — every
VM/container/instance across vCenter/ESXi, Proxmox, AWS, and GCP — and from that picture it can:

1. **Introspect** a "box" (VM/container/instance): what it is, what it's running, what files
   and data move in and out of it, what it talks to.
2. **Reproduce** it: emit the complete configuration needed to rebuild it elsewhere (IaC —
   Terraform / Ansible / cloud-init / compose).
3. **Analyze** it: surface improvements, right-sizing, and **cost-efficiency across platforms**
   (is this box cheaper as an EC2 instance, a Proxmox VM, a GCP instance, a container?).

> Explicit non-goal: **live/minute-by-minute telemetry**. This is not Datadog. We capture
> *structure and configuration* — snapshots of the stack — not time-series metrics.

## The shape of the system

```
                +-------------------+
   vCenter/ESXi |                   |
   Proxmox  --> |    Collectors     |  (provider adapters: introspect, emit Nodes)
   AWS      --> |  (per provider)   |
   GCP          |                   |
                +---------+---------+
                          |  emits
                          v
                +-------------------+
                | Unified Data Model |  <-- the contract. Provider-agnostic.
                |  (Fleet snapshot)  |      Pydantic models -> JSON Schema -> TS types
                +---------+---------+
                          |
        +-----------------+------------------+----------------------+
        v                 v                  v                      v
  +-----------+    +--------------+   +--------------+      +----------------+
  |  Store    |    |  Reproduce   |   |  Analyze     |      |  Frontend      |
  | snapshots |    |  IaC gen     |   | findings +   |      | holistic view  |
  | (JSON/db) |    | (TF/Ansible) |   | cost engine  |      | (React/TS)     |
  +-----------+    +--------------+   +--------------+      +----------------+
```

The **Unified Data Model is the keystone.** Collectors only have to produce it; everything
downstream (reproduce, analyze, frontend) only has to consume it. New providers plug in by
implementing one `Collector` interface and emitting `Node`s.

## Components

| Component       | Package                 | Milestone | Status |
|-----------------|-------------------------|-----------|--------|
| Unified model   | `fleetview.models`      | 1         | building |
| Collector base  | `fleetview.collectors`  | 1         | building |
| VMware collector| `fleetview.collectors.vmware` | 1   | building |
| Snapshot store  | `fleetview.store`       | 1         | building |
| CLI             | `fleetview.cli`         | 1         | building |
| JSON Schema gen | `fleetview.schema`      | 1         | building |
| Reproduce / IaC | `fleetview.reproduce`   | 3         | stub (interface defined) |
| Analyze / cost  | `fleetview.analyze`     | 3         | stub (interface defined) |
| Proxmox / AWS / GCP collectors | `fleetview.collectors.*` | 2 | not started |
| Frontend        | `frontend/`             | 4         | stub |

## Unified Data Model (overview)

A **`Fleet`** is one snapshot of one environment at one moment. It contains the providers it
was collected from and the nodes discovered.

```
Fleet
├── meta (id, captured_at, fleetview_version, scope)
├── providers: [Provider]            # the connections we collected from
└── nodes: [Node]                    # every box discovered
        ├── identity   (id, name, kind, native_id, provider_ref)
        ├── placement  (host, cluster, datacenter, region, zone)
        ├── compute    (vcpus, memory, cpu_model, arch, firmware)
        ├── storage    [Disk]        (size, type, backing, datastore, path)
        ├── network    [Nic]         (mac, ips, vlan, security_groups, switch)
        ├── os         (family, distro, version, kernel)
        ├── software   (packages, services, processes, listeners, containers)
        ├── flows      [DataFlow]    # what's "shuttled about": net deps, mounts, syncs
        ├── tags       {k: v}
        ├── source     (raw provider facts kept for fidelity / re-derivation)
        └── analysis   (findings + cost estimates, attached after analysis pass)
```

The model is defined once in Python (Pydantic v2). We export **JSON Schema** from it
(`fleetview schema export`) and generate **TypeScript types** for the frontend from that
schema — so backend and frontend never drift.

### Why "flows" matter

"What files are being shuttled about" is a first-class concept (`DataFlow`). A flow is an
edge: source node/endpoint → destination, with a `mechanism` (nfs_mount, rsync, scp_cron,
tcp_dependency, smb_share, s3_sync, db_connection, message_queue, ...). The fleet is therefore
a **graph**, and the frontend renders it as one. For milestone 1 the VMware collector
populates what it can see at the hypervisor layer (attached datastores, network adjacency);
deep in-guest flow discovery (mounts, cron syncs, open connections) comes with guest agents /
SSH inspection in a later milestone.

## Collector contract

Every provider implements `fleetview.collectors.base.Collector`:

```python
class Collector(ABC):
    provider_kind: ProviderKind            # vmware | proxmox | aws | gcp
    def test_connection(self) -> bool: ...
    def collect(self) -> CollectResult:    # -> Provider + [Node] + warnings
        ...
```

Collectors are **read-only** and **fidelity-preserving**: they keep the raw provider facts in
`Node.source.raw` so we can re-derive richer fields later without re-scanning.

## Snapshots & diffing

Each `collect` produces a `Fleet` snapshot, persisted by the `store` (JSON files for
milestone 1; pluggable to a real DB later). Because snapshots are immutable and timestamped,
we get **fleet diffing for free** — "what changed in the environment between Tuesday and
Friday" — without any live monitoring.

## Roadmap

- **M1 (now):** unified model + VMware/ESXi collector + JSON snapshot store + CLI + schema export.
- **M2:** Proxmox, AWS, GCP collectors against the same model.
- **M3:** reproduce engine (IaC generation) + analyze engine (findings + cross-platform cost).
- **M4:** React/TS holistic frontend (fleet graph, per-node drilldown, recommendations).
- **M5:** in-guest deep inspection (SSH/agent) for software + data-flow discovery; snapshot diffing UI.

## Elements carried over from prior work

- `whatdoesthisboxdo` — the per-box introspection logic feeds the **collectors** and the
  **reproduce** engine.
- `opsview` — the operational viewpoint/UX feeds the **frontend** holistic view.

(Both to be mined for reusable pieces once `sp00nznet` access is wired up.)
