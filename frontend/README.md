# FleetView Frontend (Milestone 4)

The holistic view: one screen that shows the **whole environment** — every node in the fleet,
its compute/OS/software, the **graph of data flows** between boxes, and the analyzer's
findings + cross-platform cost recommendations. Built to consume `Fleet` snapshots; **no live
stats** (consistent with the project's goal).

## Stack (planned)

- React + TypeScript + Vite
- Types generated from the backend's JSON Schema — never hand-written:
  ```bash
  fleetview schema export --out schema/fleet.schema.json
  npx json-schema-to-typescript schema/fleet.schema.json -o frontend/src/types/fleet.d.ts
  ```
- Graph rendering for the data-flow view (e.g. Cytoscape.js / React Flow)

## Views (planned)

1. **Fleet overview** — totals (nodes, vCPU, RAM, storage), breakdown by provider, power state.
2. **Node drilldown** — everything about one box: hardware, OS, software, flows, findings, cost.
3. **Flow graph** — nodes as vertices, `DataFlow`s as edges ("what's shuttled about").
4. **Recommendations** — fleet-wide findings sorted by estimated savings / severity.
5. **Diff** — compare two snapshots (what changed in the environment).

Scaffolding (`npm create vite@latest`) lands when we start M4. The data contract it builds
against already exists — that was the point of doing the model first.
