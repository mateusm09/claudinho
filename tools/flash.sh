#!/bin/bash
# Grava o firmware: o daemon segura a porta USB, então sai do launchd durante o upload e volta depois.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.claudinho.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PIO="${PIO:-$(command -v pio || echo "$HOME/.local/bin/pio")}"

restart() {
  if [ -f "$PLIST" ]; then
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && echo "daemon de volta" || true
  fi
}
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL"
  for _ in $(seq 50); do launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break; sleep 0.1; done
  trap restart EXIT  # volta mesmo se o upload falhar
fi
cd "$ROOT/firmware"
python3 "$ROOT/tools/mascot.py"
"$PIO" run -t upload
