from __future__ import annotations

from fleetview.models import Fleet, FleetMeta, Provider, ProviderKind
from fleetview.store import SnapshotStore


def _fleet(snap_id: str) -> Fleet:
    return Fleet(
        meta=FleetMeta(id=snap_id, scope="t"),
        providers=[Provider(kind=ProviderKind.VMWARE, instance="vc")],
        nodes=[],
    )


def test_save_load_round_trip(tmp_path):
    store = SnapshotStore(tmp_path)
    store.save(_fleet("snap-a"))
    loaded = store.load("snap-a")
    assert loaded.meta.id == "snap-a"


def test_list_and_latest(tmp_path):
    store = SnapshotStore(tmp_path)
    store.save(_fleet("snap-a"))
    store.save(_fleet("snap-b"))
    assert set(store.list_snapshots()) == {"snap-a", "snap-b"}
    assert store.latest() is not None
