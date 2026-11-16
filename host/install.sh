#!/bin/bash
# Instala o Claudinho:
#  1. hook em ~/.claude/settings.json, AO LADO dos hooks existentes (backup antes de alterar)
#  2. daemon em ~/.claudinho/app + LaunchAgent (inicia no login, reinicia se cair)
# Idempotente: rodar de novo não duplica. CLAUDINHO_NO_DAEMON=1 pula o passo 2.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
DEST="$HOME/.claudinho/bin/claudinho-hook"
EVENTS='["SessionStart","UserPromptSubmit","PreToolUse","PostToolUse","Notification","PermissionRequest","Stop","StopFailure","SessionEnd","PostToolUseFailure","PermissionDenied","ElicitationResult"]'

# Copia hook e daemon para fora do repositório (o volume externo pode não estar montado).
mkdir -p "$(dirname "$DEST")" "$HOME/.claudinho/app"
chmod 700 "$HOME/.claudinho"
install -m 755 "$HERE/claudinho-hook" "$DEST"
install -m 644 "$HERE"/{protocol,state,focus}.py "$HOME/.claudinho/app/"
install -m 755 "$HERE/claudinhod.py" "$HOME/.claudinho/app/"

[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
jq --arg cmd "$DEST" --argjson events "$EVENTS" '
  reduce $events[] as $e (.;
    .hooks[$e] = (.hooks[$e] // [])
    | if any(.hooks[$e][]?.hooks[]?; .command == $cmd) then .
      else .hooks[$e] += [{"hooks": [{"type": "command", "command": $cmd, "timeout": 2}]}]
      end)
' "$SETTINGS" > "$TMP"
jq empty "$TMP"  # valida antes de tocar no original

if [ "$(jq -S . "$SETTINGS")" = "$(jq -S . "$TMP")" ]; then
  echo "Hook já estava instalado no settings.json."
else
  # Backup só quando vai mudar, e com nome único (nunca sobrescreve um backup anterior).
  BACKUP="$SETTINGS.bak-claudinho-$(date +%Y%m%d-%H%M%S)-$$"
  cp -p "$SETTINGS" "$BACKUP"
  cat "$TMP" > "$SETTINGS"  # preserva permissões/inode do original
  echo "Hook instalado em $(echo "$EVENTS" | jq 'length') eventos. Backup: $BACKUP"
fi

# --- Daemon via launchd ----------------------------------------------------------------
[ "${CLAUDINHO_NO_DAEMON:-}" = 1 ] && exit 0
UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv não encontrado no PATH (brew install uv)"; exit 1; }
LABEL="com.claudinho.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$(dirname "$PLIST")"
sed -e "s#@UV@#$UV#g" -e "s#@HOME@#$HOME#g" "$HERE/$LABEL.plist" > "$PLIST.tmp"
plutil -lint -s "$PLIST.tmp"
mv "$PLIST.tmp" "$PLIST"

# bootout é assíncrono: espera o serviço antigo sair antes do bootstrap (senão: erro 5 / I/O error)
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
for _ in $(seq 50); do
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
  sleep 0.1
done
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Daemon carregado no launchd ($LABEL). Log: ~/.claudinho/daemon.log"
