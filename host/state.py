"""Máquina de estados das sessões: eventos de hook do Claude Code → estado exibido no device."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields

DONE_TTL_S = 10 * 60  # "done" vira "idle" (e some da tela) depois disso

# Ferramentas que, ao serem chamadas, significam "esperando o usuário" e não "trabalhando".
WAITING_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
# Notificações que pedem ação do usuário. "idle_prompt" é só um lembrete depois do Stop.
WAITING_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}


@dataclass
class Tracked:
    id: str
    cwd: str
    state: str
    since: float
    iterm: str = ""  # UUID da sessão no iTerm2 (parte depois do ':' do ITERM_SESSION_ID)
    term: str = ""  # TERM_PROGRAM
    rex_session: str = ""  # REX_SESSION / REX_BLOCK, quando roda no terminal Rex
    rex_block: str = ""
    transcript: str = ""  # caminho do JSONL da sessão (para detectar interrupções)
    offset: int = -1  # até onde o transcript já foi lido; -1 = ainda não começou
    pid: int = 0  # PID do processo `claude` (0 = desconhecido)
    last_event: float = 0.0  # epoch do último evento de hook recebido
    hidden: bool = False  # escondida pelo usuário no device; volta ao mudar de estado
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(self.cwd.rstrip("/")) or self.cwd or "?"


def _next_state(event: dict, current: str | None) -> str | None:
    """Novo estado para o evento; None = remover a sessão; current = sem mudança."""
    name = event.get("hook_event_name", "")
    if name == "SessionEnd":
        return None
    if name == "SessionStart":
        return current or "idle"
    if name == "UserPromptSubmit":
        return "working"
    if name in ("PreToolUse", "PostToolUse"):
        if name == "PreToolUse" and event.get("tool_name") in WAITING_TOOLS:
            return "waiting"
        return "working"
    if name == "PermissionRequest":
        return "waiting"
    if name == "Notification":
        ntype = event.get("notification_type", "")
        if ntype in WAITING_NOTIFICATIONS:
            return "waiting"
        if not ntype and "permission" in event.get("message", "").lower():
            return "waiting"  # versões antigas sem notification_type
        return current or "idle"
    if name == "Stop":
        return "done"
    if name == "StopFailure":
        return "error"
    return current  # SubagentStop e afins: não mudam o estado


def apply_event(sessions: dict[str, Tracked], event: dict, now: float) -> bool:
    """Aplica um evento de hook. Retorna True se algo visível mudou."""
    sid = event.get("session_id")
    if not sid:
        return False
    cur = sessions.get(sid)
    new = _next_state(event, cur.state if cur else None)

    if new is None:
        return sessions.pop(sid, None) is not None

    iterm = (event.get("_iterm") or "").split(":")[-1]
    # Raiz do projeto (CLAUDE_PROJECT_DIR) é estável; o cwd muda a cada `cd` da sessão.
    where = event.get("_project") or event.get("cwd", "")
    if cur is None:
        t = Tracked(sid, where, new, now, iterm, event.get("_term", ""),
                    event.get("_rex_session", ""), event.get("_rex_block", ""),
                    event.get("transcript_path", ""), last_event=now)
        if new in WATCHED_STATES:
            _start_watch(t)
        sessions[sid] = t
        return True

    cur.last_event = now
    if event.get("transcript_path"):
        cur.transcript = event["transcript_path"]

    changed = False
    if event.get("_project") and event["_project"] != cur.cwd:
        cur.cwd, changed = event["_project"], True
    if iterm and iterm != cur.iterm:
        cur.iterm = iterm
    if event.get("_term"):
        cur.term = event["_term"]
    if event.get("_rex_session") and event.get("_rex_block"):
        cur.rex_session, cur.rex_block = event["_rex_session"], event["_rex_block"]
    if new != cur.state:
        if new in WATCHED_STATES and cur.state not in WATCHED_STATES:
            _start_watch(cur)  # marca o offset já no evento: uma recusa rápida não escapa
        cur.state, cur.since, cur.hidden, changed = new, now, False, True
    return changed


def expire(sessions: dict[str, Tracked], now: float, done_ttl: float = DONE_TTL_S) -> bool:
    """Sessões "done" há mais de done_ttl viram "idle". Retorna True se mudou algo."""
    changed = False
    for s in sessions.values():
        if s.state == "done" and now - s.since >= done_ttl:
            s.state, s.since, changed = "idle", now, True
    return changed


def hide(sessions: dict[str, Tracked], sid: str) -> bool:
    """Usuário escondeu a sessão no device. Ela reaparece quando mudar de estado."""
    s = sessions.get(sid)
    if s and not s.hidden:
        s.hidden = True
        return True
    return False


def display_names(sessions: list[Tracked]) -> dict[str, str]:
    """Nome curto por sessão; repetidos (mesmo diretório) ganham sufixo " 2", " 3"..."""
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for s in sorted(sessions, key=lambda s: s.since):
        n = seen.get(s.name, 0) + 1
        seen[s.name] = n
        out[s.id] = s.name if n == 1 else f"{s.name} {n}"
    return out


# --- Interrupções -----------------------------------------------------------------
# Recusar uma pergunta/permissão ou apertar Esc NÃO dispara hook nenhum (Claude Code
# 2.1.325). O único rastro é uma mensagem "user" no transcript com este prefixo.
INTERRUPT_PREFIX = "[Request interrupted by user"
WATCHED_STATES = ("waiting", "working")
MAX_READ = 8 << 20  # se o transcript crescer mais que isso de uma vez, pula para o fim


def is_interrupt_line(line: bytes) -> bool:
    """True se a linha do transcript é a marca de interrupção escrita pelo Claude Code."""
    if INTERRUPT_PREFIX.encode() not in line:  # filtro barato antes do JSON
        return False
    try:
        rec = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(rec, dict) or rec.get("type") != "user":
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.startswith(INTERRUPT_PREFIX)
    if isinstance(content, list):
        return any(isinstance(c, dict) and c.get("type") == "text"
                   and str(c.get("text", "")).startswith(INTERRUPT_PREFIX) for c in content)
    return False


def _start_watch(t: Tracked) -> None:
    try:
        t.offset = os.path.getsize(t.transcript) if t.transcript else -1
    except OSError:
        t.offset = -1


def scan_transcript(t: Tracked) -> bool:
    """Lê só o que foi acrescentado ao transcript desde a última vez.
    Retorna True se encontrou uma interrupção do usuário."""
    if not t.transcript:
        return False
    try:
        size = os.path.getsize(t.transcript)
    except OSError:
        return False
    if t.offset < 0 or size < t.offset:  # primeira vez, ou arquivo truncado/recriado
        t.offset = size
        return False
    if size == t.offset:
        return False
    if size - t.offset > MAX_READ:
        t.offset = size
        return False
    with open(t.transcript, "rb") as f:
        f.seek(t.offset)
        chunk = f.read(size - t.offset)
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return False  # linha ainda incompleta: espera o resto
    t.offset += last_nl + 1
    return any(is_interrupt_line(l) for l in chunk[: last_nl + 1].splitlines())


def check_interrupts(sessions: dict[str, Tracked], now: float) -> list[str]:
    """Para sessões esperando/trabalhando, detecta interrupção e manda para "done"
    (a sessão parou e aparece como concluída; some pelo TTL ou ao ser focada).
    Sessões em outros estados param de ser acompanhadas (offset volta a -1)."""
    hit = []
    for t in sessions.values():
        if t.state not in WATCHED_STATES:
            t.offset = -1
            continue
        if scan_transcript(t):
            t.state, t.since, t.offset, t.hidden = "done", now, -1, False
            hit.append(t.id)
    return hit


# --- Sessões órfãs ------------------------------------------------------------------
STALE_NO_PID_S = 12 * 3600  # sem PID conhecido e sem eventos há tanto tempo → remove


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, só não é nosso
    return True


def prune_dead(sessions: dict[str, Tracked], now: float, alive=pid_alive) -> list[str]:
    """Remove sessões cujo processo `claude` morreu sem mandar SessionEnd (kill -9, crash)."""
    dead = [sid for sid, t in sessions.items()
            if (t.pid and not alive(t.pid))
            or (not t.pid and now - (t.last_event or t.since) > STALE_NO_PID_S)]
    for sid in dead:
        del sessions[sid]
    return dead


# --- Persistência -------------------------------------------------------------------
_FIELDS = {f.name for f in fields(Tracked)}
VALID_STATES = {"waiting", "error", "done", "working", "idle"}


def save(sessions: dict[str, Tracked], path: str) -> None:
    """Grava atômico (tmp + rename) para nunca deixar um JSON pela metade."""
    data = [asdict(t) for t in sessions.values()]
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load(path: str) -> dict[str, Tracked]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or d.get("state") not in VALID_STATES:
            continue
        try:
            t = Tracked(**{k: v for k, v in d.items() if k in _FIELDS})
        except TypeError:
            continue
        out[t.id] = t
    return out
