"""Protocolo Claudinho: codificação/decodificação das linhas JSON trocadas com o device."""
from __future__ import annotations

import json
from dataclasses import dataclass

STATES = ("waiting", "error", "done", "working", "idle")
PRIORITY = {s: i for i, s in enumerate(STATES)}
ACTIONABLE = {"waiting", "error", "done"}
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


def encode_snapshot(sessions: list[Session], seq: int, now: float) -> bytes:
    payload = {
        "snap": {
            "seq": seq,
            "sessions": [
                {"id": s.id, "name": s.name[:32], "state": s.state, "age": max(0, int(now - s.since))}
                for s in sort_sessions(sessions)
            ],
        }
    }
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if len(line) > MAX_LINE:
        # corta sessões do fim (menor prioridade) até caber
        return encode_snapshot(sort_sessions(sessions)[:-1], seq, now)
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
