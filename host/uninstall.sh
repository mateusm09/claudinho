#!/bin/bash
# Remove o Claudinho: daemon do launchd, hook do settings.json (só as entradas dele) e ~/.claudinho.
# Os outros hooks (ex.: cc-status do iTerm) ficam intactos. Idempotente.
set -euo pipefail
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
HOOK_CMD="$HOME/.claudinho/bin/claudinho-hook"
LABEL="com.claudinho.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# 1. daemon
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL" || true
  echo "Daemon parado."
fi
if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  echo "LaunchAgent removido."
fi

# 2. hook: remove só os grupos cujo comando é o do Claudinho; eventos que ficarem vazios somem
if [ -f "$SETTINGS" ]; then
  TMP="$(mktemp)"
  trap 'rm -f "$TMP"' EXIT
  jq --arg cmd "$HOOK_CMD" '
    if .hooks then
      .hooks |= (with_entries(
        .value |= map(.hooks |= map(select(.command != $cmd)) | select((.hooks | length) > 0))
      ) | with_entries(select((.value | length) > 0)))
    else . end
  ' "$SETTINGS" > "$TMP"
  jq empty "$TMP"
  if [ "$(jq -S . "$SETTINGS")" = "$(jq -S . "$TMP")" ]; then
    echo "Hook não estava no settings.json."
  else
    BACKUP="$SETTINGS.bak-claudinho-uninstall-$(date +%Y%m%d-%H%M%S)-$$"
    cp -p "$SETTINGS" "$BACKUP"
    cat "$TMP" > "$SETTINGS"
    echo "Hook removido do settings.json. Backup: $BACKUP"
  fi
fi

# 3. arquivos (hook, daemon, estado, logs, socket)
if [ -d "$HOME/.claudinho" ]; then
  rm -rf "$HOME/.claudinho"
  echo "~/.claudinho removido."
fi
echo "Pronto. O firmware continua na placa (mostra \"Aguardando o Mac...\")."
