import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import focus as F  # noqa: E402

UUID = "C862E3C6-14EE-4DE0-83D9-C5F2E4661AF1"


class Recorder:
    def __init__(self, osa=(0, "ok"), open_rc=0):
        self.calls, self.osa, self.open_rc = [], osa, open_rc

    def osascript(self, script, *args):
        self.calls.append(("osa", args))
        return self.osa

    def run(self, cmd, **kw):
        self.calls.append(("open", tuple(cmd)))
        return type("P", (), {"returncode": self.open_rc})()


def patch(monkeypatch, rec):
    monkeypatch.setattr(F, "_osascript", rec.osascript)
    monkeypatch.setattr(F.subprocess, "run", rec.run)


def test_focuses_exact_session_passing_uuid_as_argv(monkeypatch):
    rec = Recorder()
    patch(monkeypatch, rec)
    assert F.focus(UUID, "iTerm.app") == "session"
    assert rec.calls == [("osa", (UUID,))]


def test_falls_back_to_app_when_session_gone(monkeypatch):
    rec = Recorder(osa=(0, "notfound"))
    patch(monkeypatch, rec)
    assert F.focus(UUID, "iTerm.app") == "app"
    assert rec.calls[-1] == ("open", ("/usr/bin/open", "-a", "iTerm"))


def test_rejects_non_uuid_without_osascript(monkeypatch):
    rec = Recorder()
    patch(monkeypatch, rec)
    assert F.focus('" & (do shell script "x") & "', "iTerm.app") == "app"
    assert all(kind != "osa" for kind, _ in rec.calls)


def test_other_terminal_and_unknown(monkeypatch):
    rec = Recorder()
    patch(monkeypatch, rec)
    assert F.focus("", "Apple_Terminal") == "app"
    assert F.focus("", "") == "none"


RS = "session:01a1eeb7-5610-7416-8f87-d73299d8a2a6"
RB = "block:01a1eeb7-5613-7449-9334-2c6f89240328"


def test_rex_focus_uses_rex_cli_and_activates_app(monkeypatch):
    calls = []

    def fake_rex(*args):
        calls.append(args)
        out = '{"block":{"window_id":"window:x"}}' if args[0] == "block" else ""
        return type("P", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    monkeypatch.setattr(F, "_rex", fake_rex)
    rec = Recorder()
    patch(monkeypatch, rec)
    assert F.focus("", "rex", RS, RB) == "session"
    assert calls == [("focus", "-s", RS, RB)]
    assert ("osa", (RS,)) in rec.calls  # show da sessão via AppleScript, ID por argv
    assert not any(c[0] == "open" for c in rec.calls)


def test_rex_show_failure_still_activates_app(monkeypatch):
    monkeypatch.setattr(F, "_rex", lambda *a: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    rec = Recorder(osa=(1, ""))
    patch(monkeypatch, rec)
    assert F.focus("", "rex", RS, RB) == "session"
    assert ("open", ("/usr/bin/open", "-a", "Rex Beta")) in rec.calls


def test_rex_rejects_malformed_ids(monkeypatch):
    monkeypatch.setattr(F, "_rex", lambda *a: (_ for _ in ()).throw(AssertionError("não deveria chamar")))
    patch(monkeypatch, Recorder())
    assert F.focus("", "", "x; rm -rf /", RB) == "none"
