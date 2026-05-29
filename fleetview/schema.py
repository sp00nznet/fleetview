"""Export the unified data model as JSON Schema.

This is the bridge to the frontend: `fleetview schema export` writes the Fleet JSON Schema,
from which we generate TypeScript types (see frontend/README.md). Keeping the schema generated
— never hand-written — guarantees backend and frontend never drift.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Fleet


def fleet_json_schema() -> dict:
    return Fleet.model_json_schema()


def export(out_path: str | Path = "schema/fleet.schema.json") -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fleet_json_schema(), indent=2), encoding="utf-8")
    return path
