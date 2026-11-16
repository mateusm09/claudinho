#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyserial>=3.5"]
# ///
"""claudinhod: ponte entre as sessões do Claude Code e o ESP-BOX (USB CDC)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
from logging.handlers import RotatingFileHandler
import sys
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state  # noqa: E402
from focus import focus  # noqa: E402
from protocol import Session, decode_line, encode_snapshot  # noqa: E402

ESPRESSIF_VID = 0x303A
HEARTBEAT_S = 30
HOME_DIR = Path.home() / ".claudinho"
SOCK_PATH = HOME_DIR / "sock"
STATE_PATH = HOME_DIR / "state.json"
PRUNE_EVERY_S = 10
SOL_LOCAL, LOCAL_PEERPID = 0, 0x002  # macOS: PID do processo do outro lado do socket Unix
log = logging.getLogger("claudinhod")


class Store:
    """Estado das sessões, protegido por lock. Qualquer mudança acorda o enviador e é salva."""

    def __init__(self, state_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._state_path = state_path
        self._tracked: dict[str, state.Tracked] = state.load(str(state_path)) if state_path else {}
        if self._tracked:
            log.info("estado restaurado: %d sessões", len(self._tracked))
        self.seq = 0
        self.changed = threading.Event()

    def _save_locked(self) -> None:
        if not self._state_path:
            return
        try:
            state.save(self._tracked, str(self._state_path))
        except OSError as e:
            log.warning("não consegui salvar o estado: %s", e)

    def _notify_locked(self) -> None:
        self._save_locked()
        self.changed.set()

    def replace_all(self, sessions: list[state.Tracked]) -> None:
        with self._lock:
            self._tracked = {s.id: s for s in sessions}
        self.changed.set()  # modo --fake: não salva

    def needs_pid(self, sid: str) -> bool:
        with self._lock:
            t = self._tracked.get(sid)
            return bool(sid) and (t is None or not t.pid)

    def apply(self, event: dict, claude_pid: int = 0) -> None:
        sid = event.get("session_id", "")
        with self._lock:
            changed = state.apply_event(self._tracked, event, time.time())
            t = self._tracked.get(sid)
            if t and claude_pid and not t.pid:
                t.pid = claude_pid
                log.info("sessão %s ↔ claude pid %d", t.name, claude_pid)
                changed_pid = True
            else:
                changed_pid = False
            if changed:
                log.info("%s %s → %s", event.get("hook_event_name"), t.name if t else sid,
                         t.state if t else "removida")
                self._notify_locked()
            elif changed_pid:
                self._save_locked()

    def tick(self, prune: bool = False) -> None:
        with self._lock:
            now = time.time()
            changed = state.expire(self._tracked, now)
            for sid in state.check_interrupts(self._tracked, now):
                log.info("interrupção detectada no transcript: %s → done", self._tracked[sid].name)
                changed = True
            if prune:
                names = {sid: t.name for sid, t in self._tracked.items()}
                for sid in state.prune_dead(self._tracked, now):
                    log.info("sessão %s sumiu (processo morreu) → removida", names[sid])
                    changed = True
            if changed:
                self._notify_locked()
            elif prune:
                self._save_locked()  # offsets dos transcripts andam sem mudança visível

    def get(self, sid: str) -> state.Tracked | None:
        with self._lock:
            return self._tracked.get(sid)

    def mark_seen(self, sid: str) -> None:
        with self._lock:
            if state.mark_seen(self._tracked, sid, time.time()):
                self._notify_locked()

    def snapshot_line(self) -> bytes:
        with self._lock:
            self.seq += 1
            names = state.display_names(list(self._tracked.values()))
            visible = [Session(t.id, names[t.id], t.state, t.since)
                       for t in self._tracked.values() if t.state != "idle"]
            return encode_snapshot(visible, self.seq, time.time())


def find_claude_pid(pid: int, max_depth: int = 8) -> int:
    """Sobe a árvore de processos a partir de `pid` até achar o `claude`.
    Uma única chamada ao `ps` (a árvore inteira) para não atrasar o hook."""
    try:
        out = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,args="],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    procs: dict[int, tuple[int, str]] = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    for _ in range(max_depth):
        if pid not in procs:
            return 0
        ppid, args = procs[pid]
        if os.path.basename(args.split(" ", 1)[0]) == "claude":
            return pid
        if ppid <= 1:
            return 0
        pid = ppid
    return 0


def serve_hooks(store: Store, sock_path: Path) -> None:
    """Recebe eventos do claudinho-hook: uma conexão por evento, JSON no corpo."""
    sock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(sock_path))
    except OSError as e:
        log.critical("não consegui abrir o socket %s: %s", sock_path, e)
        os._exit(1)  # sem socket o daemon é inútil; launchd reinicia
    os.chmod(sock_path, 0o600)
    srv.listen(16)
    log.info("escutando hooks em %s", sock_path)
    while True:
        conn, _ = srv.accept()
        try:
            peer_pid = conn.getsockopt(SOL_LOCAL, LOCAL_PEERPID)  # o `nc` do hook
        except OSError:
            peer_pid = 0
        with conn:
            conn.settimeout(2)
            buf = b""
            try:
                # O hook manda uma linha (jq -c). Lê até o \n e fecha logo: o nc do macOS
                # não faz half-close, então esperar EOF atrasaria cada hook em ~1 s.
                while b"\n" not in buf and len(buf) < 1 << 20:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except OSError:
                pass
            try:
                event = json.loads(buf.split(b"\n", 1)[0] or b"null")
            except json.JSONDecodeError:
                log.warning("evento inválido do hook")
                continue
            if not isinstance(event, dict):
                continue
            # PID do `claude` tem que ser resolvido COM a conexão aberta: ao fechar, o nc e o
            # shell do hook terminam e a cadeia de processos some. Só no 1º evento da sessão.
            claude_pid = 0
            if peer_pid and store.needs_pid(event.get("session_id", "")):
                claude_pid = find_claude_pid(peer_pid)
        log.debug("hook: %s", event)
        store.apply(event, claude_pid)


def run_ticker(store: Store) -> None:
    n = 0
    while True:
        time.sleep(1)  # barato: só um stat() por sessão esperando/trabalhando
        n += 1
        try:
            store.tick(prune=n % PRUNE_EVERY_S == 0)
        except Exception:  # o ticker nunca pode morrer
            log.exception("erro no ticker")


def find_port(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for p in list_ports.comports():
        if p.vid == ESPRESSIF_VID:
            return p.device
    return None


class DeviceLink:
    """Mantém a conexão serial: reconecta, responde ao hello, envia snapshots."""

    def __init__(self, store: Store, port: str | None, on_focus) -> None:
        self.store = store
        self.port_arg = port
        self.on_focus = on_focus
        self.ser: serial.Serial | None = None
        self._wlock = threading.Lock()

    def send_snapshot(self) -> None:
        if not self.ser:
            return
        line = self.store.snapshot_line()
        with self._wlock:
            try:
                self.ser.write(line)
                self.ser.flush()
                log.debug("-> %s", line.decode().strip())
            except (serial.SerialException, OSError) as e:
                log.warning("falha ao escrever: %s", e)

    def _open(self, dev: str) -> serial.Serial:
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = dev, 115200, 1
        s.dtr = False  # evita reset (no USB-Serial-JTAG nem sempre basta)
        s.rts = False
        s.open()
        return s

    def run_reader(self) -> None:
        while True:
            dev = find_port(self.port_arg)
            if not dev:
                time.sleep(2)
                continue
            try:
                self.ser = self._open(dev)
                log.info("conectado em %s", dev)
                self.send_snapshot()
                while True:
                    raw = self.ser.readline()
                    if not raw:
                        continue
                    msg = decode_line(raw)
                    if msg is None:
                        continue
                    log.debug("<- %s", msg)
                    if "hello" in msg:
                        log.info("hello do device (%s)", msg.get("board"))
                        self.send_snapshot()
                    elif "focus" in msg:
                        self.on_focus(str(msg["focus"]))
            except (serial.SerialException, OSError) as e:
                log.warning("conexão perdida: %s", e)
            finally:
                if self.ser:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                self.ser = None
            time.sleep(2)

    def run_sender(self) -> None:
        while True:
            self.store.changed.wait(timeout=HEARTBEAT_S)
            self.store.changed.clear()
            self.send_snapshot()


FAKE_SCENARIOS = {
    "mix": [("contatto-services", "waiting", 75), ("claudinho", "working", 12),
            ("ikarians-app", "done", 340), ("tkd-page", "error", 30), ("neopris", "idle", 5000)],
    "waiting": [("claudinho", "waiting", 3)],
    "working": [("claudinho", "working", 3)],
    "done": [("claudinho", "done", 3)],
    "idle": [("claudinho", "idle", 3)],
    "empty": [],
}
# --fake cycle: alterna os cenários (e um período sem host, para ver o "dormindo")
CYCLE = ["idle", "working", "waiting", "done", "error", "empty", "mix"]


def fake_sessions(name: str) -> list[state.Tracked]:
    now = time.time()
    return [state.Tracked(f"fake-{i}", f"/fake/{n}", st, now - age)
            for i, (n, st, age) in enumerate(FAKE_SCENARIOS[name])]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="porta serial (padrão: autodetect VID 0x303A)")
    ap.add_argument("--fake", nargs="?", const="mix", choices=sorted([*FAKE_SCENARIOS, "cycle"]),
                    help="envia sessões falsas em vez de escutar os hooks")
    ap.add_argument("--sock", type=Path, default=SOCK_PATH, help="socket Unix dos hooks")
    ap.add_argument("--state", type=Path, default=STATE_PATH, help="arquivo de estado persistido")
    ap.add_argument("--log-file", type=Path, help="log em arquivo com rotação (para o launchd)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    fmt = "%(asctime)s %(levelname)s %(message)s"
    level = logging.DEBUG if args.verbose else logging.INFO
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(args.log_file, maxBytes=1 << 20, backupCount=3)
        handler.setFormatter(logging.Formatter(fmt))
        logging.basicConfig(level=level, handlers=[handler])
    else:
        logging.basicConfig(level=level, format=fmt)

    store = Store(None if args.fake is not None else args.state)
    if args.fake == "cycle":
        def cycle() -> None:
            while True:
                for name in CYCLE:
                    log.info("cenário: %s", name)
                    store.replace_all(fake_sessions(name))
                    time.sleep(5)
        threading.Thread(target=cycle, daemon=True).start()
    elif args.fake is not None:
        store.replace_all(fake_sessions(args.fake))
    else:
        threading.Thread(target=serve_hooks, args=(store, args.sock), daemon=True).start()
        threading.Thread(target=run_ticker, args=(store,), daemon=True).start()

    def on_focus(sid: str) -> None:
        t = store.get(sid)
        if not t:
            log.info("focus pedido para sessão desconhecida: %s", sid)
            return
        store.mark_seen(sid)  # "done"/"error" vistos somem da tela

        def run() -> None:
            t0 = time.monotonic()
            result = focus(t.iterm, t.term)
            log.info("focus %s (%s) → %s em %.0f ms", t.name, t.state, result, (time.monotonic() - t0) * 1000)

        threading.Thread(target=run, daemon=True).start()  # não bloqueia a leitura da serial

    link = DeviceLink(store, args.port, on_focus=on_focus)
    threading.Thread(target=link.run_sender, daemon=True).start()
    try:
        link.run_reader()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
