# Plano de implementação: Claudinho

## Visão geral
O Claudinho é um assistente de mesa que roda no ESP-BOX (ESP32-S3), ligado ao Mac por USB. Ele mostra o estado de cada sessão do Claude Code (trabalhando, esperando input/permissão, terminou) junto com um mascote animado em pixel art. Ao tocar numa sessão, ou no botão principal, a aba/janela do iTerm2 daquela sessão vem para a frente.

## O que já existe no ambiente
- ESP-BOX conectado em `/dev/cu.usbmodem1401` (Espressif "USB JTAG_serial debug unit", ou seja, o USB nativo do S3, sem chip UART).
- Terminal: **iTerm2**. A variável `ITERM_SESSION_ID` (`w0t2p0:<UUID>`) chega ao processo do hook, então dá para focar exatamente a sessão certa.
- `~/.claude/settings.json` já tem o hook `cc-status` do iTerm2 em todos os eventos. **Ele precisa continuar funcionando**: o Claudinho entra como um hook *adicional*.
- Já disponíveis: `python3`, `uv`, `jq`, `nc`, `brew`. Ainda **não** instalados: PlatformIO, esptool e ESP-IDF.
- `/Volumes/Mello/repos/claudinho/` está vazio, então o projeto começa do zero.

## Arquitetura

```
Claude Code ──hook (stdin JSON)──▶ claudinho-hook ──unix socket──▶ claudinhod (daemon Python, launchd)
                                                                     │  ▲
                                                    snapshot JSON ▼  │ {"focus": id}
                                                                  ESP-BOX (USB CDC)
                                                                     │
                                         osascript ◀── focus ────────┘  → iTerm2 seleciona a sessão
```

## Decisões de arquitetura
- **Firmware com PlatformIO + Arduino + LovyanGFX.** A configuração do S3-BOX fica explícita em `firmware/src/board.h` (ILI9342C, luz de fundo no GPIO45 e touch TT21100 em 0x24), porque o autodetect falhou na T1. É muito menos código que ESP-IDF + esp-bsp + LVGL. O framebuffer de 320×240 fica num sprite na PSRAM e a tela é redesenhada inteira, sem flicker.
- **Transporte: USB CDC com JSON, uma mensagem por linha, nos dois sentidos.** Não depende de Wi-Fi nem de configuração de rede. O host envia o *snapshot completo* a cada mudança (é idempotente e se recupera sozinho depois de uma reconexão). O device envia `{"focus":"<id>"}` e `{"hello":1}` quando dá boot, e o host responde com o snapshot.
- **Hook pequeno e que nunca bloqueia.** Ele lê o JSON do stdin, acrescenta `ITERM_SESSION_ID`, `TERM_PROGRAM` e `PPID`, envia por `nc -U` com timeout curto e **sempre termina com exit 0**. Se o daemon estiver fora do ar, o Claude não percebe nada.
- **O estado fica no daemon, não no hook.** Mapeamento de eventos:
  `SessionStart`→idle · `UserPromptSubmit`/`PreToolUse`→working · `Notification`/`PermissionRequest`→**waiting** · `Stop`→**done** · `StopFailure`→error · `SessionEnd`→remove.
  Uma sessão em `done` volta a `idle` quando ela é focada pelo device ou quando chega um novo prompt.
- **Focar a sessão via AppleScript no iTerm2:** percorre as sessões até achar o `unique id` igual ao UUID e então dá `select` na janela, aba e sessão. Para outros terminais (`TERM_PROGRAM` diferente de iTerm), o fallback é só `activate` no app.
- **Prioridade na tela:** waiting > error > done > working > idle. O botão grande "Ir para" leva à sessão de maior prioridade.
- **Mascote:** um sprite pixel art original no estilo do mascote do Claude Code (bloquinho laranja com olhos), com 4 animações ligadas ao estado agregado: idle (piscando), working (pulando/digitando), waiting (acenando com "!"), done (feliz).

## Lista de tarefas
Os detalhes de cada tarefa estão em `tasks/todo.md`.

### Fase 1: Fundação (riscos de hardware primeiro)
- [x] T1: Toolchain + "hello" no display e no touch do ESP-BOX
- [x] T2: Fatia vertical com dados falsos: daemon → serial → lista renderizada na tela

### Checkpoint 1
- [x] Firmware compila e grava; o touch responde; o daemon mostra um snapshot falso na tela

### Fase 2: Fluxo real de ponta a ponta
- [x] T3: Hook + máquina de estados do daemon com sessões reais do Claude
- [x] T4: Toque → focar a sessão no iTerm2

### Checkpoint 2
- [x] Abrir 2 sessões reais e ver working/waiting/done; tocar e cair na aba certa

### Fase 3: Mascote e robustez
- [ ] T5: Mascote animado ligado ao estado
- [ ] T6: launchd + reconexão USB + limpeza de sessões órfãs
- [ ] T7: Alertas (flash/beep), README e instalador

### Checkpoint 3
- [ ] Sobrevive a desplugar/replugar, a reboot do Mac e ao `kill` de sessões; README permite reinstalar do zero

## Riscos e mitigações
| Risco | Impacto | Mitigação |
|---|---|---|
| Variante da placa (BOX, BOX-3 ou Lite) tem touch/pinos diferentes | Alto | **Resolvido na T1:** o autodetect falhou (caía no BOX-3 com a luz de fundo errada). `firmware/src/board.h` configura o S3-BOX à mão |
| Abrir a porta USB-Serial-JTAG causa reset (DTR/RTS) | Médio | Desligar DTR/RTS no pyserial. Mesmo com reset, o protocolo `hello`→snapshot se recupera |
| macOS pede permissão de Automação (osascript → iTerm) | Médio | Primeiro teste manual na T4 para aceitar o prompt TCC. Documentar no README |
| Hook duplicado quebrar o `cc-status` existente | Alto | Adicionar só uma nova entrada no array `hooks` de cada evento. Fazer backup do settings.json antes. Validar com `jq` |
| Sessão morre sem `SessionEnd` (kill, crash) | Baixo | O daemon verifica periodicamente se o PID do Claude está vivo e remove a sessão se não estiver |
| Muitas sessões não cabem em 320×240 | Baixo | Lista com rolagem por swipe, ordenada por prioridade |
| Latência do hook atrasando o Claude | Médio | `nc -U -w1`, sem Python no hook, sempre exit 0 |

## Decisões do Mateus (2026-11-16)
1. Placa: ESP32-S3-BOX (original), a confirmar pelo autodetect na T1.
2. Só iTerm2 por enquanto. O fallback "activate app" basta para outros terminais.
3. Sessões `done` somem sozinhas após um timeout (padrão 10 min, configurável) ou ao serem focadas.
4. Sim, beep no alto-falante (codec ES8311) na transição para `waiting`.
