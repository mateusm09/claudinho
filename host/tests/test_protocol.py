import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import MAX_LINE, Session, decode_line, encode_snapshot, sort_sessions  # noqa: E402


def _decode_snap(line: bytes) -> dict:
    assert line.endswith(b"\n")
    return json.loads(line)["snap"]


def test_snapshot_sorted_by_priority_then_age():
    now = 1000.0
    ss = [
        Session("a", "idle-proj", "idle", 900),
        Session("b", "work", "working", 950),
        Session("c", "late-wait", "waiting", 990),
        Session("d", "early-wait", "waiting", 800),
        Session("e", "fin", "done", 970),
    ]
    snap = _decode_snap(encode_snapshot(ss, seq=3, now=now))
    assert snap["seq"] == 3
    assert [s["id"] for s in snap["sessions"]] == ["d", "c", "e", "b", "a"]
    assert snap["sessions"][0]["age"] == 200


def test_age_never_negative_and_name_truncated():
    snap = _decode_snap(encode_snapshot([Session("x", "n" * 50, "idle", 2000)], 1, now=1000))
    assert snap["sessions"][0]["age"] == 0
    assert len(snap["sessions"][0]["name"]) == 32


def test_snapshot_respects_max_line():
    ss = [Session(f"id-{i:04d}-" + "x" * 30, "p" * 32, "working", i) for i in range(200)]
    line = encode_snapshot(ss, 1, now=1000)
    assert len(line) <= MAX_LINE
    assert _decode_snap(line)["sessions"]


def test_invalid_state_rejected():
    with pytest.raises(ValueError):
        Session("x", "y", "sleeping", 0)


@pytest.mark.parametrize(
    "raw",
    [b"ESP-ROM:esp32s3-20210327\r\n", b"{not json\n", b"\xff\xfe\n", b"[1,2]\n", b"\n"],
)
def test_decode_ignores_garbage(raw):
    assert decode_line(raw) is None


def test_decode_valid():
    assert decode_line(b'{"focus":"abc"}\r\n') == {"focus": "abc"}


def test_sort_is_stable_api():
    assert sort_sessions([]) == []


def test_done_and_error_carry_local_time_others_do_not():
    import time
    since = 1_800_000_000.0
    ss = [Session("d", "a", "done", since), Session("e", "b", "error", since),
          Session("w", "c", "waiting", since), Session("k", "d", "working", since)]
    by_id = {s["id"]: s for s in _decode_snap(encode_snapshot(ss, 1, now=since + 90))["sessions"]}
    expected = time.strftime("%H:%M", time.localtime(since))
    assert by_id["d"]["at"] == expected and by_id["e"]["at"] == expected
    assert "at" not in by_id["w"] and "at" not in by_id["k"]


def test_usage_is_optional_in_snapshot():
    assert "usage" not in _decode_snap(encode_snapshot([], 1, now=0))
    snap = _decode_snap(encode_snapshot([], 1, now=0, usage=(42, 5400)))
    assert snap["usage"] == {"pct": 42, "reset_in": 5400}
