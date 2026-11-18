import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state import DONE_TTL_S, Tracked, apply_event, display_names, expire, hide  # noqa: E402


def ev(name, sid="s1", **kw):
    return {"hook_event_name": name, "session_id": sid, "cwd": "/repos/claudinho", **kw}


def run(*events, now=100.0):
    ss: dict[str, Tracked] = {}
    for e in events:
        apply_event(ss, e, now)
    return ss


def test_full_lifecycle():
    ss = {}
    assert apply_event(ss, ev("SessionStart", _iterm="w0t2p0:ABC-123", _term="iTerm.app"), 1)
    assert ss["s1"].state == "idle" and ss["s1"].iterm == "ABC-123" and ss["s1"].name == "claudinho"
    apply_event(ss, ev("UserPromptSubmit"), 2)
    assert ss["s1"].state == "working"
    apply_event(ss, ev("PermissionRequest", tool_name="Bash"), 3)
    assert ss["s1"].state == "waiting"
    apply_event(ss, ev("PostToolUse", tool_name="Bash"), 4)
    assert ss["s1"].state == "working"
    apply_event(ss, ev("Stop"), 5)
    assert ss["s1"].state == "done" and ss["s1"].since == 5
    assert apply_event(ss, ev("SessionEnd"), 6)
    assert ss == {}


def test_waiting_tools_and_notifications():
    assert run(ev("PreToolUse", tool_name="AskUserQuestion"))["s1"].state == "waiting"
    assert run(ev("PreToolUse", tool_name="ExitPlanMode"))["s1"].state == "waiting"
    assert run(ev("PreToolUse", tool_name="Read"))["s1"].state == "working"
    assert run(ev("Notification", notification_type="permission_prompt"))["s1"].state == "waiting"
    assert run(ev("Notification", message="Claude needs your permission to use Bash"))["s1"].state == "waiting"


def test_idle_prompt_keeps_done():
    ss = run(ev("UserPromptSubmit"), ev("Stop"), ev("Notification", notification_type="idle_prompt"))
    assert ss["s1"].state == "done"


def test_stop_failure_is_error_and_subagent_stop_ignored():
    assert run(ev("UserPromptSubmit"), ev("StopFailure"))["s1"].state == "error"
    assert run(ev("UserPromptSubmit"), ev("SubagentStop"))["s1"].state == "working"


def test_same_state_does_not_reset_since_or_report_change():
    ss = {}
    apply_event(ss, ev("PreToolUse", tool_name="Read"), 10)
    assert not apply_event(ss, ev("PostToolUse", tool_name="Read"), 20)
    assert ss["s1"].since == 10


def test_ignores_events_without_session_id():
    ss = {}
    assert not apply_event(ss, {"hook_event_name": "Stop"}, 1)
    assert ss == {}


def test_session_end_for_unknown_session():
    assert not apply_event({}, ev("SessionEnd"), 1)


def test_done_expires_to_idle():
    ss = run(ev("Stop"), now=0)
    assert not expire(ss, DONE_TTL_S - 1)
    assert expire(ss, DONE_TTL_S)
    assert ss["s1"].state == "idle"


def test_hide_until_state_changes():
    ss = run(ev("Stop"))
    assert hide(ss, "s1") and ss["s1"].hidden
    assert not hide(ss, "s1")  # já escondida
    assert not hide(ss, "nope")
    apply_event(ss, ev("Notification", notification_type="idle_prompt"), 200)  # não muda estado
    assert ss["s1"].hidden
    apply_event(ss, ev("UserPromptSubmit"), 201)  # mudou de estado → reaparece
    assert not ss["s1"].hidden


def test_hidden_working_session_reappears_when_waiting():
    ss = run(ev("UserPromptSubmit"))
    hide(ss, "s1")
    apply_event(ss, ev("PostToolUse", tool_name="Read"), 2)
    assert ss["s1"].hidden
    apply_event(ss, ev("PermissionRequest"), 3)
    assert not ss["s1"].hidden and ss["s1"].state == "waiting"


def test_display_names_disambiguates():
    a = Tracked("a", "/r/proj", "working", 1)
    b = Tracked("b", "/r/proj", "done", 2)
    c = Tracked("c", "/r/other", "done", 3)
    assert display_names([b, c, a]) == {"a": "proj", "b": "proj 2", "c": "other"}


def test_project_dir_wins_over_cwd():
    ss = {}
    apply_event(ss, ev("SessionStart", cwd="/r/proj/sub", _project="/r/proj"), 1)
    assert ss["s1"].name == "proj"
    apply_event(ss, ev("PreToolUse", tool_name="Read", cwd="/r/proj/deep/er"), 2)
    assert ss["s1"].name == "proj"


def test_cwd_fallback_does_not_rename():
    ss = run(ev("SessionStart", cwd="/r/first"))
    apply_event(ss, ev("Stop", cwd="/r/first/sub"), 2)
    assert ss["s1"].name == "first"


# --- interrupções via transcript ---------------------------------------------------
import json  # noqa: E402

from state import check_interrupts, is_interrupt_line  # noqa: E402


def jl(obj) -> bytes:
    return json.dumps(obj).encode() + b"\n"


REJECT_RESULT = jl({"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "is_error": True, "tool_use_id": "toolu_1",
     "content": "The user doesn't want to proceed with this tool use."}]}})
INTERRUPT_TOOL = jl({"type": "user", "message": {"role": "user", "content": [
    {"type": "text", "text": "[Request interrupted by user for tool use]"}]}})
INTERRUPT_ESC = jl({"type": "user", "message": {"role": "user", "content": "[Request interrupted by user]"}})
# falsos positivos: a frase aparece citada em mensagens do assistente / blobs de API
ASSISTANT_QUOTE = jl({"type": "assistant", "message": {"content": [
    {"type": "text", "text": "[Request interrupted by user] é a marca"}]}})
API_BLOB = jl({"type": "api-request-blob", "content": "... [Request interrupted by user for tool use] ..."})
USER_QUOTE = jl({"type": "user", "message": {"content": [{"type": "text", "text": "o que é [Request interrupted by user]?"}]}})


def test_interrupt_line_detection():
    assert is_interrupt_line(INTERRUPT_TOOL)
    assert is_interrupt_line(INTERRUPT_ESC)
    for line in (REJECT_RESULT, ASSISTANT_QUOTE, API_BLOB, USER_QUOTE, b"{broken [Request interrupted by user\n"):
        assert not is_interrupt_line(line), line


def _session(tmp_path, state="waiting"):
    tr = tmp_path / "t.jsonl"
    tr.write_bytes(jl({"type": "user", "message": {"content": "[Request interrupted by user]"}}) * 3)  # histórico antigo
    return {"s1": Tracked("s1", "/r/p", state, 0, transcript=str(tr))}, tr


def test_old_history_is_ignored_and_new_interrupt_detected(tmp_path):
    ss, tr = _session(tmp_path)
    assert check_interrupts(ss, 1) == []  # primeira leitura só marca o offset
    with tr.open("ab") as f:
        f.write(ASSISTANT_QUOTE + REJECT_RESULT + INTERRUPT_TOOL)
    assert check_interrupts(ss, 2) == ["s1"]
    assert ss["s1"].state == "done" and ss["s1"].offset == -1 and ss["s1"].since == 2


def test_partial_line_waits_for_completion(tmp_path):
    ss, tr = _session(tmp_path, "working")
    check_interrupts(ss, 1)
    with tr.open("ab") as f:
        f.write(INTERRUPT_ESC[:20])
    assert check_interrupts(ss, 2) == []
    with tr.open("ab") as f:
        f.write(INTERRUPT_ESC[20:])
    assert check_interrupts(ss, 3) == ["s1"]


def test_not_watched_in_done_state_and_missing_file(tmp_path):
    ss, tr = _session(tmp_path, "done")
    with tr.open("ab") as f:
        f.write(INTERRUPT_ESC)
    assert check_interrupts(ss, 1) == [] and ss["s1"].offset == -1
    ss["s1"].state, ss["s1"].transcript = "waiting", str(tmp_path / "nope.jsonl")
    assert check_interrupts(ss, 2) == []


def test_hook_event_records_transcript_path():
    ss = run(ev("PreToolUse", tool_name="AskUserQuestion", transcript_path="/x/t.jsonl"))
    assert ss["s1"].transcript == "/x/t.jsonl"


def test_fast_rejection_right_after_event_is_caught(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_bytes(b'{"type":"user","message":{"content":"oi"}}\n')
    ss = {}
    apply_event(ss, ev("PreToolUse", tool_name="AskUserQuestion", transcript_path=str(tr)), 1)
    with tr.open("ab") as f:  # recusa antes de qualquer tick
        f.write(INTERRUPT_TOOL)
    assert check_interrupts(ss, 2) == ["s1"]


def test_interrupted_session_expires_like_done(tmp_path):
    ss, tr = _session(tmp_path)
    check_interrupts(ss, 0)
    with tr.open("ab") as f:
        f.write(INTERRUPT_ESC)
    check_interrupts(ss, 10)
    assert ss["s1"].state == "done"
    assert not expire(ss, 10 + DONE_TTL_S - 1)
    assert expire(ss, 10 + DONE_TTL_S) and ss["s1"].state == "idle"


# --- órfãs e persistência ---------------------------------------------------------------
from state import STALE_NO_PID_S, load, prune_dead, save  # noqa: E402


def test_prune_dead_by_pid_and_staleness():
    ss = {
        "alive": Tracked("alive", "/r/a", "working", 0, pid=111, last_event=0),
        "dead": Tracked("dead", "/r/b", "waiting", 0, pid=222, last_event=0),
        "nopid-fresh": Tracked("nopid-fresh", "/r/c", "done", 0, last_event=100),
        "nopid-old": Tracked("nopid-old", "/r/d", "done", 0, last_event=0),
    }
    removed = prune_dead(ss, now=STALE_NO_PID_S + 50, alive=lambda pid: pid == 111)
    assert sorted(removed) == ["dead", "nopid-old"]
    assert sorted(ss) == ["alive", "nopid-fresh"]


def test_save_load_roundtrip_keeps_offset_and_pid(tmp_path):
    p = str(tmp_path / "state.json")
    ss = {"s1": Tracked("s1", "/r/p", "waiting", 5, "UUID", "iTerm.app", "/t.jsonl", offset=1234, pid=99,
                        last_event=6)}
    save(ss, p)
    back = load(p)
    assert back["s1"] == ss["s1"]
    assert not list(tmp_path.glob(".state-*"))  # sem temporários sobrando


def test_load_tolerates_missing_corrupt_and_unknown_fields(tmp_path):
    assert load(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load(str(bad)) == {}
    odd = tmp_path / "odd.json"
    odd.write_text('[{"id":"a","cwd":"/x","state":"done","since":1,"campo_futuro":7}, {"lixo":1}, 3, {"id":"b","cwd":"/y","state":"zumbi","since":1}]')
    assert list(load(str(odd))) == ["a"]


def test_apply_event_tracks_last_event():
    ss = {}
    apply_event(ss, ev("UserPromptSubmit"), 10)
    apply_event(ss, ev("PostToolUse", tool_name="Read"), 20)  # mesmo estado, mas é atividade
    assert ss["s1"].last_event == 20 and ss["s1"].since == 10


def test_rex_ids_are_tracked():
    ss = {}
    apply_event(ss, ev("SessionStart", _rex_session="session:a", _rex_block="block:b"), 1)
    assert (ss["s1"].rex_session, ss["s1"].rex_block) == ("session:a", "block:b")
