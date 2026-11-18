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


def _usage(store):
    return json.loads(store.snapshot_line())["snap"].get("usage")


def test_usage_reaches_snapshot_and_expires(tmp_path):
    import time
    store = d.Store(None)
    assert _usage(store) is None
    store.set_usage(41.6, time.time() + 3600)
    u = _usage(store)
    assert u["pct"] == 42 and 3590 <= u["reset_in"] <= 3600
    store.set_usage(150, time.time() - 1)  # janela já resetada: não mostra
    assert _usage(store) is None


def test_usage_only_wakes_sender_when_visible_value_changes():
    import time
    store = d.Store(None)
    reset = time.time() + 3600
    store.set_usage(10.2, reset)
    store.changed.clear()
    store.set_usage(10.4, reset)  # mesmo % arredondado
    assert not store.changed.is_set()
    store.set_usage(11, reset)
    assert store.changed.is_set()
