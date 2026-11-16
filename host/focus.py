"""Traz para a frente a janela/aba/sessão do terminal onde a sessão do Claude roda."""
from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger("claudinhod.focus")

ITERM_BUNDLE = "com.googlecode.iterm2"
UUID_RE = re.compile(r"^[0-9A-Fa-f-]{36}$")

# O UUID entra via argv (nunca interpolado no script) → sem injeção de AppleScript.
ITERM_SCRIPT = f'''
on run argv
  set target to item 1 of argv
  tell application id "{ITERM_BUNDLE}"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if unique id of s is target then
            if miniaturized of w then set miniaturized of w to false
            tell w to select
            tell t to select
            tell s to select
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "notfound"
end run
'''

# TERM_PROGRAM → app para o fallback "só ativar o app"
TERM_APPS = {
    "iTerm.app": "iTerm",
    "Apple_Terminal": "Terminal",
    "vscode": "Visual Studio Code",
    "ghostty": "Ghostty",
    "WezTerm": "WezTerm",
}


def _osascript(script: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["/usr/bin/osascript", "-e", script, *args],
                       capture_output=True, text=True, timeout=5)
    if p.returncode != 0:
        log.warning("osascript falhou (%s): %s", p.returncode, p.stderr.strip())
    return p.returncode, p.stdout.strip()


def focus(iterm_uuid: str, term: str) -> str:
    """Retorna "session" (aba exata), "app" (só ativou o app) ou "none"."""
    if iterm_uuid and UUID_RE.match(iterm_uuid):
        rc, out = _osascript(ITERM_SCRIPT, iterm_uuid)
        if rc == 0 and out == "ok":
            return "session"
        log.info("sessão iTerm %s não encontrada (%s); ativando o app", iterm_uuid, out)
    app = TERM_APPS.get(term) or ("iTerm" if iterm_uuid else "")
    if app:
        rc = subprocess.run(["/usr/bin/open", "-a", app], capture_output=True).returncode
        return "app" if rc == 0 else "none"
    return "none"
