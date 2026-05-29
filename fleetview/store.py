"""Snapshot persistence.

Milestone 1 uses timestamped JSON files on disk — immutable, human-diffable, git-friendly.
The interface is deliberately small so a real database backend can replace it later without
touching callers. Because snapshots are immutable + timestamped, fleet diffing comes for free.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import Fleet


class SnapshotStore:
    def __init__(self, root: str | Path = "snapshots") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, snapshot_id: str) -> Path:
        safe = snapshot_id.replace(":", "-").replace("/", "-")
        return self.root / f"{safe}.json"

    def save(self, fleet: Fleet) -> Path:
        path = self._path(fleet.meta.id)
        path.write_text(fleet.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, snapshot_id: str) -> Fleet:
        path = self._path(snapshot_id)
        return Fleet.model_validate_json(path.read_text(encoding="utf-8"))

    def load_path(self, path: str | Path) -> Fleet:
        return Fleet.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def list_snapshots(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def latest(self) -> Optional[Fleet]:
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return self.load_path(files[0]) if files else None
