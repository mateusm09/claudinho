"""Protocolo Claudinho: codificação/decodificação das linhas JSON trocadas com o device."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

STATES = ("waiting", "error", "done", "working", "idle")
PRIORITY = {s: i for i, s in enumerate(STATES)}
ACTIONABLE = {"waiting", "error", "done"}
# Estados "parados": o device mostra o horário em que a sessão chegou nele, não um contador.
SHOW_TIME = {"done", "error"}
MAX_LINE = 4096


@dataclass
class Session:
    id: str
    name: str
    state: str
    since: float  # epoch (s) da última mudança de estado

    def __post_init__(self) -> None:
        if self.state not in PRIORITY:
            raise ValueError(f"estado inválido: {self.state}")


def sort_sessions(sessions: list[Session]) -> list[Session]:
    """Prioridade por estado; dentro do mesmo estado, a mais antiga primeiro."""
    return sorted(sessions, key=lambda s: (PRIORITY[s.state], s.since))


def encode_snapshot(sessions: list[Session], seq: int, now: float,
                    usage: tuple[int, int] | None = None) -> bytes:
    """`usage` = (% usado da janela de 5h, segundos até ela resetar); None = desconhecido."""
    def item(s: Session) -> dict:
        d = {"id": s.id, "name": s.name[:32], "state": s.state, "age": max(0, int(now - s.since))}
        if s.state in SHOW_TIME:
            d["at"] = time.strftime("%H:%M", time.localtime(s.since))  # horário local do Mac
        return d

    payload = {"snap": {"seq": seq, "sessions": [item(s) for s in sort_sessions(sessions)]}}
    if usage is not None:
        payload["snap"]["usage"] = {"pct": usage[0], "reset_in": usage[1]}
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if len(line) > MAX_LINE:
        # corta sessões do fim (menor prioridade) até caber
        return encode_snapshot(sort_sessions(sessions)[:-1], seq, now, usage)
    return line


def decode_line(raw: bytes) -> dict | None:
    """Decodifica uma linha vinda do device. Ignora lixo (log de boot da ROM etc.)."""
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if not text.startswith("{"):
        return None
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None
