import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claudinhod as d  # noqa: E402


def ids(store):
    return [s["id"] for s in json.loads(store.snapshot_line())["snap"]["sessions"]]


def test_hidden_and_idle_sessions_are_not_sent(tmp_path):
    store = d.Store(tmp_path / "state.json")
    for sid, ev in [("a", "Stop"), ("b", "UserPromptSubmit"), ("c", "SessionStart")]:
        store.apply({"hook_event_name": ev, "session_id": sid, "cwd": f"/r/{sid}"})
    assert sorted(ids(store)) == ["a", "b"]  # c está idle
    store.hide("a")
    assert ids(store) == ["b"]
    store.apply({"hook_event_name": "UserPromptSubmit", "session_id": "a"})  # mudou de estado
    assert sorted(ids(store)) == ["a", "b"]


def test_hidden_flag_survives_restart(tmp_path):
    store = d.Store(tmp_path / "state.json")
    store.apply({"hook_event_name": "Stop", "session_id": "a", "cwd": "/r/a"})
    store.hide("a")
    assert ids(d.Store(tmp_path / "state.json")) == []
