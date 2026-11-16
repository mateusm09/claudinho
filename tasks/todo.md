# Claudinho: tarefas

## Task 1: Toolchain + hello no display e no touch
**Descrição:** Instalar o PlatformIO (via `uv tool install platformio`) e criar `firmware/` com Arduino + LovyanGFX (autodetect). O firmware mostra "Claudinho" na tela e envia pela serial as coordenadas de cada toque, além do nome do painel detectado.

**Critérios de aceite:**
- [x] `pio run -t upload` grava em `/dev/cu.usbmodem1401` sem erro
- [x] A tela mostra "Claudinho" com a orientação correta
- [x] Cada toque imprime `{"touch":[x,y]}` na serial; o boot imprime a variante detectada

**Verificação:**
- [x] Build: `cd firmware && pio run`
- [x] Manual: `pio device monitor`, tocar nos 4 cantos e conferir as coordenadas (0–320 × 0–240)

**Dependências:** nenhuma
**Arquivos:** `firmware/platformio.ini`, `firmware/src/main.cpp`, `firmware/src/board.h`
**Nota:** a placa é o S3-BOX original (touch TT21100 @0x24). O autodetect do LovyanGFX cai no BOX-3 (backlight no GPIO47 → tela preta), então `board.h` configura a placa explicitamente: backlight no GPIO45 e Y do touch invertido. Abrir a porta serial reseta o chip, por isso o protocolo precisa de hello → resend.
**Escopo:** S

## Task 2: Fatia vertical com snapshot falso
**Descrição:** Definir o protocolo em `docs/protocol.md`. Criar o daemon `host/claudinhod.py` (script uv, pyserial) que abre a serial com DTR/RTS desligados, responde ao `hello` e envia um snapshot fixo. O firmware faz o parse com ArduinoJson e renderiza a lista: nome do projeto, cor do estado e tempo desde a última mudança.

**Critérios de aceite:**
- [x] O snapshot `{"snap":{"seq","sessions":[{"id","name","state","age"}]}}` aparece na tela
- [x] Depois de um reset do device, o snapshot reaparece sozinho (hello → resend)
- [x] Linhas JSON inválidas são ignoradas sem travar

**Verificação:**
- [x] Teste: `uv run pytest host/tests/test_protocol.py` (encode/decode)
- [x] Manual: `uv run host/claudinhod.py --fake` e conferir a tela

**Notas:**
- Corrigido underflow de `millis()`: o snapshot chegava com `rxMillis` > `now` → o device achava que o host tinha sumido e mandava `hello` a cada heartbeat.
- O RX do HWCDC (core 2.0.x) para de receber se o buffer estoura durante o `pushSprite`. O buffer passou para 16 KB e o host limita cada linha a 4 KB. Teste: `robust.py`/`robust2.py` (lixo, linha de 6 KB, snapshot colado).
- Testes do host: `cd host && uv run --with pytest --with pyserial python -m pytest -q tests` (11 passam).

**Dependências:** T1
**Arquivos:** `docs/protocol.md`, `host/claudinhod.py`, `host/tests/test_protocol.py`, `firmware/src/main.cpp`, `firmware/src/ui.cpp`
**Escopo:** M

## Checkpoint 1
- [x] Firmware compila e grava; o touch responde; o snapshot falso aparece
- [x] Revisar com o Mateus antes de mexer no `~/.claude/settings.json`

## Task 3: Hook real + máquina de estados
**Descrição:** Criar `host/claudinho-hook` (bash + jq + `nc -U -w1`, sempre exit 0), que envia o evento junto com `ITERM_SESSION_ID`, `TERM_PROGRAM` e `PPID` para `~/.claudinho/sock`. O daemon passa a escutar o socket, aplica o mapeamento de eventos para estados e empurra o snapshot. Um script de instalação adiciona o hook ao lado do `cc-status`, com backup.

**Critérios de aceite:**
- [x] Sessão real: prompt → working; pedido de permissão → waiting; fim → done; `/exit` → some
- [x] O `cc-status` do iTerm continua funcionando (status na aba)
- [x] Com o daemon parado, o Claude funciona normalmente e o hook leva menos de 100 ms

**Verificação:**
- [x] Teste: `uv run pytest host/tests/test_state.py` (transições de estado)
- [x] Manual: 2 sessões do Claude em abas diferentes, observando a tela

**Notas:**
- Hook instalado (`SubagentStop` fica de fora). Backup: `~/.claude/settings.json.bak-claudinho-20261116-131638-33928`. O hook roda de `~/.claudinho/bin/` (fora do volume externo).
- O hook manda só `hook_event_name, session_id, cwd, tool_name, notification_type, message` + env: `tool_input` e `transcript_path` não saem da máquina do Claude.
- Nome = basename de `CLAUDE_PROJECT_DIR` (o `cwd` muda a cada `cd`).
- `AskUserQuestion`/`ExitPlanMode` → waiting; `idle_prompt` mantém done; sessões idle não vão para a tela.
- **Recusar uma pergunta/permissão ou apertar Esc não dispara hook nenhum** (confirmado com o log bruto no Claude Code 2.1.325: depois do `PermissionRequest` o próximo evento é o `UserPromptSubmit`). Solução: enquanto a sessão está waiting/working, o daemon lê só os bytes novos do `transcript_path` a cada 1 s e procura uma mensagem `type:"user"` com texto começando por `[Request interrupted by user`. A sessão então vira **done** (decisão do Mateus: mostrar como concluída, não sumir). O offset é marcado no próprio evento do hook, para uma recusa rápida não escapar.
- Hook também em `PostToolUseFailure`, `PermissionDenied`, `ElicitationResult` (12 eventos). Por ora esses não mudam o estado.
- Log bruto de depuração: `touch ~/.claudinho/debug-raw` liga, e os eventos vão para `~/.claudinho/raw-events.jsonl`. Está desligado.
- Latência do hook: ~10 ms com daemon, ~7 ms sem. O daemon lê até `\n` porque o `nc` do macOS não faz half-close.
- 23 testes passam.

**Dependências:** T2
**Arquivos:** `host/claudinho-hook`, `host/claudinhod.py`, `host/state.py`, `host/install.sh`, `host/tests/test_state.py`
**Escopo:** M

## Task 4: Toque → focar a sessão
**Descrição:** No firmware, tocar numa linha envia `{"focus":id}`, e o botão "Ir para" envia o id de maior prioridade. O daemon executa um AppleScript que seleciona a janela, a aba e a sessão do iTerm2 pelo UUID, com fallback de `activate` para outros terminais. Uma sessão `done` volta a `idle` depois de focada.

**Critérios de aceite:**
- [x] Tocar numa sessão `waiting` traz a aba certa do iTerm2 para a frente, mesmo com outra janela ativa
- [x] O botão "Ir para" escolhe waiting > error > done
- [x] O toque dá feedback visual imediato (highlight)

**Verificação:**
- [x] Manual: 3 sessões em 2 janelas do iTerm, tocando em cada uma
- [x] Manual: aceitar o prompt de Automação do macOS na primeira execução

**Notas:**
- `focus.py`: o AppleScript procura o `unique id` da sessão no iTerm2 e seleciona a janela, a aba e a sessão (desminimiza se precisar). O UUID vai via argv e é validado por regex, então não há injeção. Leva ~430 ms.
- Fallback: `open -a <app>` pelo `TERM_PROGRAM`.
- Focar marca `done`/`error` como vistos (`idle`), e a sessão some da tela.
- 27 testes passam (4 de focus).

**Dependências:** T3
**Arquivos:** `host/focus.py`, `host/claudinhod.py`, `firmware/src/ui.cpp`
**Escopo:** S

## Checkpoint 2
- [x] Fluxo de ponta a ponta funcionando com sessões reais
- [x] Revisar com o Mateus

## Task 5: Mascote animado
**Descrição:** Sprite pixel art original (32×32, escalado 3×) gerado como array RGB565 em `firmware/src/mascot.h` a partir de um PNG com `tools/png2c.py`. Quatro animações (idle, working, waiting, done) a ~8 fps, escolhidas pelo estado agregado, com cabeçalho "Claudinho".

**Critérios de aceite:**
- [ ] A animação é fluida, sem flicker (sprite com double buffer)
- [ ] A animação troca dentro de 1 s quando o estado agregado muda
- [ ] O toque continua responsivo durante a animação

**Verificação:**
- [x] Build: `pio run`
- [ ] Manual: forçar cada estado com `claudinhod.py --fake <estado>`

**Notas:**
- `tools/mascot.py` desenha os quadros em código: um grid 16×14 com paleta de 8 cores. Gera `firmware/src/mascot.h` (40 quadros, ~9 KB de flash) e `assets/mascot-preview.png` (a folha para revisão). A implementação mudou em relação ao plano original de PNG→C via `png2c.py`.
- Animações: idle (pisca), working (pula/anda), waiting (acena + "!" âmbar), done (^ ^ + brilhos verdes), error (olhos X), sleep (olhos fechados + "Z", quando não há host).
- Animação = estado da sessão de maior prioridade. Lista vazia ou sem host → mascote grande (escala 7) no centro.
- A tela só redesenha quando o quadro muda (`ui::animDue`).
- `claudinhod.py --fake cycle` alterna os cenários a cada 5 s.

**Dependências:** T2 (pode correr em paralelo com T3/T4)
**Arquivos:** `assets/mascot.png`, `tools/png2c.py`, `firmware/src/mascot.h`, `firmware/src/ui.cpp`
**Escopo:** M

## Task 6: launchd + robustez
**Descrição:** LaunchAgent `com.claudinho.daemon` (KeepAlive). O daemon reconecta quando o USB é desplugado/replugado, procura a porta pelo VID 303a, remove sessões cujo PID morreu e loga em `~/.claudinho/log`.

**Critérios de aceite:**
- [ ] Depois do login, o Claudinho funciona sem comando manual
- [ ] Desplugar e replugar volta ao normal em menos de 5 s
- [x] `kill -9` numa sessão do Claude a remove da tela em menos de 30 s

**Verificação:**
- [ ] Manual: `launchctl kickstart`, desplugar/replugar, kill

**Notas:**
- `install.sh` copia hook + daemon para `~/.claudinho/{bin,app}` e carrega o LaunchAgent: `RunAtLoad`, `KeepAlive`, `uv run --script`, log com rotação em `~/.claudinho/daemon.log`. O `bootout` é assíncrono, então o instalador espera o serviço sair antes do `bootstrap` (senão dá erro 5).
- Estado persistido em `~/.claudinho/state.json` (gravação atômica), incluindo o offset de cada transcript: uma recusa com o daemon fora do ar é detectada quando ele volta.
- PID do `claude`: `LOCAL_PEERPID` do socket (o `nc`) + subir a árvore com um único `ps -A`. Tem que ser **antes** de fechar a conexão, senão a cadeia de processos some. Só no 1º evento da sessão.
- Poda a cada 10 s: PID morto → remove. Sem PID e sem eventos há 12 h → remove. `kill -9` testado com um falso `claude`: removido em 8 s.
- O primeiro focus via launchd levou 4,3 s (prompt de Automação do macOS); depois ~390 ms.
- `tools/flash.sh` grava o firmware tirando o daemon do launchd durante o upload.
- 38 testes passam.

**Dependências:** T3
**Arquivos:** `host/com.claudinho.daemon.plist`, `host/claudinhod.py`, `host/install.sh`
**Escopo:** S

## Task 7: Alertas + README
**Descrição:** Flash de borda e, se você quiser, beep no alto-falante quando alguma sessão entra em `waiting`. O README cobre a instalação, as permissões e a desinstalação (incluindo remover o hook sem tocar no `cc-status`).

**Critérios de aceite:**
- [ ] Alerta só na transição para waiting (sem repetir)
- [x] `install.sh` / `uninstall.sh` idempotentes

**Notas:**
- `audio.cpp`: o codec ES8311 é configurado pelo I2C do LovyanGFX (porta 1, compartilhada com o touch; usar o `Wire` brigaria pelos pinos), com I2S a 16 kHz e o amplificador no GPIO46. O som são duas notas (Mi6 → Si6) com envelope, tocadas numa task FreeRTOS.
- A task de som no núcleo 0 atrasava ~1,5 s a saída da serial (USB-Serial-JTAG). No núcleo 1 isso não acontece.
- O alerta só toca quando um id ENTRA em waiting, nunca no 1º snapshot depois do boot. A borda pisca em âmbar por 1,5 s.
- Tocar no cabeçalho liga/desliga o som (salvo em NVS); quando mudo, aparece um ícone de alto-falante riscado.
- `uninstall.sh` remove só as entradas do Claudinho (testado numa cópia: as 10 do cc-status ficam, o resto do arquivo fica idêntico, e reinstalar volta ao arquivo original).

**Dependências:** T5, T6
**Arquivos:** `README.md`, `host/uninstall.sh`, `firmware/src/ui.cpp`
**Escopo:** S

## Checkpoint 3
- [ ] Todos os critérios atendidos; reinstalação do zero seguindo o README funciona
