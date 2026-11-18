# Claudinho

Assistente de mesa para o Claude Code, rodando num **ESP32-S3-BOX** ligado ao Mac por USB.

- Mostra cada sessão do Claude Code e o estado dela: **esperando** (âmbar), **erro** (vermelho), **pronto** (verde) ou **trabalhando** (azul).
- **Tocar numa sessão**, ou no botão "Ir para", traz a aba exata do iTerm2 ou do Rex para a frente.
- Uma **barra no rodapé** mostra o uso do limite de 5h (verde, âmbar acima de 60%, vermelho acima de 85%) e quando ele reseta. O ícone de olho à esquerda mostra ou esconde a barra.
- Toca um **beep** e pisca a borda quando uma sessão passa a esperar input. Tocar no cabeçalho liga e desliga o som.
- O mascote é animado e reage ao estado mais urgente. Quando o Mac não está conectado, ele dorme.

```
Claude Code ─hook─▶ claudinho-hook ─socket─▶ claudinhod (launchd) ─USB─▶ ESP32-S3-BOX
                                                   ▲                         │
                              iTerm2 / Rex ◀─osascript─── {"focus": id} ◀───┘ (toque)
```

## Requisitos

- macOS, iTerm2 (ou o terminal Rex) e Claude Code. Testado na versão 2.1.325.
- `uv`, `jq` e PlatformIO. Instalação: `brew install uv jq && uv tool install platformio`.
- ESP32-S3-BOX, o **original**, com touch TT21100. O BOX-3 e o BOX-Lite usam outros pinos; veja `firmware/src/board.h`.

## Instalação

```bash
# 1. firmware (com o BOX plugado)
./tools/flash.sh

# 2. hook + daemon
./host/install.sh
```

O `install.sh`:
- **acrescenta** o hook em `~/.claude/settings.json`. Os hooks que já existem, como o `cc-status` do iTerm, continuam lá. Antes de alterar, ele faz um backup `settings.json.bak-claudinho-*`.
- configura o **statusline** do Claude Code (`claudinho-statusline`), que entrega o uso do limite de 5h. Se você já tinha um statusline, ele continua rodando por dentro do nosso e volta ao original na desinstalação. O uso só atualiza quando o Claude Code redesenha o statusline (a cada resposta), e aparece `--` até a primeira.
- copia o hook e o daemon para `~/.claudinho/`, assim nada depende do repositório depois de instalado.
- carrega o LaunchAgent `com.claudinho.daemon`, que inicia o daemon no login e o reinicia se cair.

Pode rodar de novo quantas vezes quiser; nada é duplicado. Use `CLAUDINHO_NO_DAEMON=1` para instalar só o hook.

**Na primeira vez que você tocar numa sessão**, o macOS pede permissão para o daemon controlar o iTerm ou o Rex. Aceite. Se negar por engano, libere depois em *Ajustes do Sistema → Privacidade e Segurança → Automação*.

### Terminal Rex

Funciona sem configuração extra: o hook lê `REX_SESSION` e `REX_BLOCK` do ambiente. Ao tocar numa sessão, o daemon:

1. roda `rex focus` para deixar a aba certa ativa;
2. pede ao app, por AppleScript (`show`), para mostrar a sessão e vir para a frente, mesmo que você esteja em outra sessão. Isso **não** exige o Remote Control do Rex.

O nome do app está fixo como `Rex Beta` (`REX_APP` em `host/focus.py`); ajuste se usar outra versão. Sessões já abertas só passam a ter o foco do Rex depois do próximo evento de hook, então rode o `install.sh` de novo e reinicie-as.

## Desinstalação

```bash
./host/uninstall.sh
```

Remove o daemon, as entradas do Claudinho no `settings.json` e a pasta `~/.claudinho`. Os outros hooks não são tocados, e o script faz backup antes de alterar o arquivo.

## Como os estados são detectados

| Evento do Claude Code | Estado |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | trabalhando |
| `PermissionRequest`, notificação `permission_prompt` ou `elicitation_dialog`, `PreToolUse` de `AskUserQuestion` ou `ExitPlanMode` | **esperando** |
| `Stop` | **pronto** |
| `StopFailure` | erro |
| `SessionEnd` | some da tela |

Três casos que não seguem a tabela:
- **Recusar uma pergunta ou permissão, ou apertar Esc, não dispara nenhum hook.** Enquanto uma sessão está esperando ou trabalhando, o daemon lê só os bytes novos do transcript dela e procura a marca `[Request interrupted by user…]`. Quando encontra, a sessão passa a **pronto**.
- **Uma sessão pronta some** depois de 10 minutos. Tocar nela leva você até a aba, mas ela continua na lista.
- **O ícone de olho riscado** no fim de cada linha esconde a sessão. Ela volta sozinha quando muda de estado; por exemplo, se passar a esperar input, você não perde o alerta.
- **Uma sessão cujo processo morreu** (`kill -9`, crash) é removida em até ~10 s. O daemon descobre o PID do `claude` pelo socket do hook.

O hook manda ao daemon só o evento, o id da sessão, a pasta do projeto, o caminho do transcript e a aba do iTerm. O conteúdo de prompts, comandos e arquivos não sai do Claude Code.

## Estrutura

| Caminho | O que é |
|---|---|
| `firmware/` | PlatformIO + Arduino + LovyanGFX. `board.h` (pinos do S3-BOX), `ui.cpp` (tela), `audio.cpp` (ES8311/I2S), `mascot.h` (gerado) |
| `host/claudinhod.py` | daemon: socket dos hooks, máquina de estados, serial, foco |
| `host/state.py` | estados, interrupções via transcript, poda de órfãs, persistência |
| `host/focus.py` | Seleciona a sessão no iTerm2 (AppleScript, pelo UUID) ou no Rex (`rex focus`, por `REX_SESSION`/`REX_BLOCK`) |
| `host/claudinho-statusline` | statusline: repassa `rate_limits.five_hour` ao daemon (e roda o statusline anterior, se havia) |
| `host/claudinho-hook` | hook (bash + jq + nc): ~10 ms e sempre `exit 0` |
| `tools/mascot.py` | desenho do mascote: gera `firmware/src/mascot.h` e `assets/mascot-preview.png` |
| `tools/flash.sh` | grava o firmware, tirando o daemon do caminho durante o upload |
| `docs/protocol.md` | protocolo USB entre o host e a placa (JSON, uma mensagem por linha) |

## Desenvolvimento

```bash
cd host && uv run --with pytest --with pyserial python -m pytest -q tests   # testes do host
uv run --script host/claudinhod.py --fake cycle                              # demonstra todos os estados (pare o launchd antes)
python3 tools/mascot.py                                                      # depois de mexer no mascote
./tools/flash.sh                                                             # grava (regera o mascote)
tail -f ~/.claudinho/daemon.log                                              # log do daemon
touch ~/.claudinho/debug-raw                                                 # grava o JSON bruto dos hooks em ~/.claudinho/raw-events.jsonl
```

Para rodar o daemon à mão, primeiro tire o do launchd: `launchctl bootout gui/$(id -u)/com.claudinho.daemon`. Para devolver: `./host/install.sh`.

## Problemas conhecidos

- **Tela preta com o autodetect do LovyanGFX.** Ele confunde o S3-BOX com o BOX-3 e acende a luz de fundo no pino errado. Por isso a placa é configurada explicitamente em `board.h`.
- **A recepção USB do core Arduino 2.0.x trava se o buffer estoura.** O buffer da placa é de 16 KB e o host limita cada linha a 4 KB.
- **Abrir a porta serial reinicia a placa.** O protocolo se recupera: a placa manda `hello` e o host responde com o snapshot.
