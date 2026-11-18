#!/bin/bash
# Grava o firmware: o daemon segura a porta USB, então sai do launchd durante o upload e volta depois.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.claudinho.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PIO="${PIO:-$(command -v pio || echo "$HOME/.local/bin/pio")}"

restart() {
  [ -f "$PLIST" ] || return 0
  for _ in 1 2 3 4 5; do
    launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && { echo "daemon de volta"; return 0; }
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || sleep 1
  done
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && echo "daemon de volta" \
    || echo "AVISO: daemon não voltou; rode ./host/install.sh" >&2
}
# o daemon pode estar no launchd ou não; se o plist existe, sempre tenta devolvê-lo no fim
[ -f "$PLIST" ] && trap restart EXIT  # volta mesmo se o upload falhar
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL"
  for _ in $(seq 50); do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 0.1; done
fi
cd "$ROOT/firmware"
python3 "$ROOT/tools/mascot.py"
"$PIO" run -t upload
