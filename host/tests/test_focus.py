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
