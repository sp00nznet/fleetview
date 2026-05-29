# Heritage & Consolidation Plan

FleetView consolidates two existing tools. This document maps their components onto FleetView's
architecture so we **reuse** rather than rewrite. (Both repos were analyzed at consolidation
time; paths below are in those source repos.)

## whatdoesthisboxdo — per-box introspection, cost, IaC

A server analyzer (local / SSH / WinRM) that builds a per-server picture, estimates cloud cost,
and generates IaC to recreate the box.

| Their component | Path | Maps to FleetView |
|---|---|---|
| `analysis_data` dict (processes/services/ports/packages/files) | `analyzer.py` | `models.SoftwareInventory`, `Compute`, `OSInfo` (we type what they kept as dicts) |
| `RemoteSystemAnalyzer` / SSH+WinRM executors | `analyzers/remote_analyzer.py`, `connectors/*` | **in-guest deep inspection** for collectors (M5) — software, config files, flows |
| Service `connections` / `listening_ports` | `analyzers/remote_analyzer.py` | `models.DataFlow` (TCP dependencies) + `ListeningPort` |
| Captured config files | file analyzers | `models.ConfigFile` (added to the model for reproduce fidelity) |
| `PatternLearner` (server-role detection) | `analyzers/pattern_learner.py` | `models.AppFingerprint` + an analyzer |
| `CostEstimator` + AWS/GCP/Azure pricing tables | `generators/cost_estimator.py` | **`analyze.CrossPlatformCostAnalyzer`** (M3) — drop-in pricing data + `models.CostEstimate` |
| Terraform/Ansible/Packer generators | `generators/*` | **`reproduce.Reproducer`** implementations (M3) — `models.Node` → `Artifact`s |
| Datadog connector | `connectors/datadog_connector.py` | **dropped** — live metrics are an explicit non-goal |

**Biggest direct wins:** the cost pricing tables + the per-platform IaC generators. Both consume
specs we already model; they become the bodies of the `analyze` and `reproduce` engines.

## opsview — fleet enumeration, SSH probes, topology

Fleet observability for vCenter/Proxmox estates + standalone Linux: enumerate hosts, SSH-probe
each, render a tabbed web UI with a Cytoscape mount/flow topology and analysis.

| Their component | Path | Maps to FleetView |
|---|---|---|
| `Host` model + state persistence (timestamped history) | `orchestrator/inventory.py`, `state.py` | `models.Node` + `store.SnapshotStore` (we already do immutable timestamped snapshots) |
| `enumerate_vcenter()` (pyvmomi) | `orchestrator/vcenter.py` | already reimplemented as **`collectors.vmware`** ✅ |
| `enumerate_proxmox()` (PVE REST, token/ticket auth, LXC+QEMU) | `orchestrator/proxmox.py` | **`collectors.proxmox`** (M2) — direct port |
| OneFS/Isilon collector | `orchestrator/onefs.py` | storage-provider node type (later) |
| SSH probes: mounts/disk/services/docker/ports/apps | `probes/linux/*` | **in-guest deep inspection** for collectors (M5) |
| Mount/export model + topology graph | `orchestrator/analysis.py` | `models.DataFlow` graph — this **is** "what files are shuttled about" |
| Analyzers: redundant / similar / circular / orphans / single-client | `orchestrator/analysis.py` | **fleet-graph analyzers** in `analyze` (M3) — consolidation findings |
| `topology_elements()` → Cytoscape nodes/edges | `orchestrator/analysis.py` | **frontend flow-graph** export (M4) |
| `triage()` baseline-vs-current drift | `orchestrator/triage.py` | **snapshot diffing** ("what changed") — natural fit for immutable snapshots |
| Flask + vanilla-JS tabbed UI (Cytoscape/Mermaid) | `web/*` | rebuilt as **React/TS frontend** (M4); reuse the server-side topology/analysis logic |

**Biggest direct wins:** the Proxmox enumerator (drops straight into M2) and the mount/export
topology + graph analyzers (become the flow model + the consolidation findings).

## What this means for the roadmap

- **M2 (collectors):** port `enumerate_proxmox` → `collectors.proxmox`; add `collectors.aws`
  (boto3) and `collectors.gcp`. All emit the existing `Node` model.
- **M3 (reproduce + analyze):** lift the IaC generators and cost tables from whatdoesthisboxdo;
  lift the graph analyzers from opsview. Both already have a home in the model.
- **M4 (frontend):** React/TS over the JSON Schema; reuse opsview's `topology_elements` shape
  for the flow graph.
- **M5 (deep inspection):** SSH/WinRM executors + probes from both repos populate software,
  config files, and data flows that the hypervisor/cloud layer can't see.

## Notable scope notes

- **Azure** already exists in whatdoesthisboxdo's cost + IaC. Not in the current `ProviderKind`
  (user scope is vCenter/Proxmox/AWS/GCP) but trivially addable when wanted.
- **No live metrics.** whatdoesthisboxdo's Datadog/metrics-monitor paths are intentionally
  excluded — FleetView captures structure, not time-series.
