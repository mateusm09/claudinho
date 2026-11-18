"""Traz para a frente a janela/aba/sessão do terminal onde a sessão do Claude roda."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

log = logging.getLogger("claudinhod.focus")

ITERM_BUNDLE = "com.googlecode.iterm2"
UUID_RE = re.compile(r"^[0-9A-Fa-f-]{36}$")
REX_ID_RE = re.compile(r"^(session|block):[0-9a-f-]{36}$")
REX_APP = "Rex Beta"
REX_FALLBACK_BIN = "~/Library/Application Support/com.superlogical.rex/RexServer/Versions/Current/Rex Server.app/Contents/MacOS/rex"

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

# O Rex identifica sessões como "<host>/session:<uuid>"; casa pelo sufixo. ID via argv (sem injeção).
# `show` troca a sessão visível e traz o app para a frente, sem precisar do Remote Control.
REX_SHOW_SCRIPT = f'''
on run argv
  set suffix to "/" & item 1 of argv
  tell application "{REX_APP}"
    repeat with s in sessions
      set sid to id of s
      if sid ends with suffix then
        show sid
        return "ok"
      end if
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
    "rex": REX_APP,
    "WezTerm": "WezTerm",
}


def _osascript(script: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["/usr/bin/osascript", "-e", script, *args],
                       capture_output=True, text=True, timeout=5)
    if p.returncode != 0:
        log.warning("osascript falhou (%s): %s", p.returncode, p.stderr.strip())
    return p.returncode, p.stdout.strip()


def _rex_bin() -> str | None:
    found = shutil.which("rex") or os.path.expanduser(REX_FALLBACK_BIN)
    return found if os.access(found, os.X_OK) else None


def _rex(*args: str) -> subprocess.CompletedProcess | None:
    exe = _rex_bin()
    if not exe:
        return None
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("rex falhou: %s", e)
        return None


def focus_rex(rex_session: str, rex_block: str) -> bool:
    """Seleciona o painel/aba da sessão no Rex e traz o app para a frente."""
    if not (REX_ID_RE.match(rex_session) and REX_ID_RE.match(rex_block)):
        return False
    p = _rex("focus", "-s", rex_session, rex_block)
    if p is None or p.returncode != 0:
        log.info("rex focus falhou: %s", (p.stderr.strip() if p else "rex não encontrado"))
        return False
    # `rex focus` deixou a aba certa ativa no servidor; agora o app precisa mostrar essa sessão.
    rc, out = _osascript(REX_SHOW_SCRIPT, rex_session)
    if rc == 0 and out == "ok":
        return True
    log.info("show da sessão Rex falhou (%s %s); só ativando o app", rc, out)
    return subprocess.run(["/usr/bin/open", "-a", REX_APP], capture_output=True).returncode == 0


def focus(iterm_uuid: str, term: str, rex_session: str = "", rex_block: str = "") -> str:
    """Retorna "session" (aba exata), "app" (só ativou o app) ou "none"."""
    if rex_session and rex_block and focus_rex(rex_session, rex_block):
        return "session"
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
