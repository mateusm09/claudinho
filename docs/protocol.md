# Protocolo Claudinho (USB CDC)

Transporte: a porta USB-Serial-JTAG nativa do ESP32-S3 (`/dev/cu.usbmodem*`, VID `0x303A`), a 115200 bps. A velocidade é ignorada, porque a porta é USB nativa.
Formato: **um objeto JSON por linha**, terminado em `\n`, em UTF-8, com no máximo 4 KB por linha.
Linhas que não são JSON válido (por exemplo, o log de boot da ROM) são ignoradas pelos dois lados.

## Device → host

| Mensagem | Quando |
|---|---|
| `{"hello":1,"board":"ESP32-S3-BOX","fw":"0.2.0"}` | A cada 2 s, enquanto ainda não recebeu nenhum snapshot (depois de boot ou reset) |
| `{"focus":"<id>"}` | Toque numa linha da lista ou no botão "Ir para" |
| `{"ack":<seq>}` | Depois de aplicar um snapshot |

## Host → device

```json
{"snap":{"seq":12,"sessions":[
  {"id":"9f1c…","name":"claudinho","state":"waiting","age":42}
]}}
```

- `seq`: contador que só cresce. Serve para depuração e para o `ack`.
- `sessions`: já vem **ordenada por prioridade** pelo host. O device não reordena.
- `state`: um dos valores `waiting` | `error` | `done` | `working` | `idle`.
- `age`: segundos desde a última mudança de estado. O device continua somando o tempo localmente entre um snapshot e outro.
- `name`: o nome curto (basename do `cwd`), que o device trunca para caber na tela.

O host envia o snapshot completo:
1. ao receber um `hello`;
2. a cada mudança de estado;
3. a cada 30 s, como heartbeat. Assim o device corrige o `age` e detecta que o host sumiu (mostra "sem host" depois de 90 s sem snapshot).

## Prioridade (host)
`waiting` > `error` > `done` > `working` > `idle`. Dentro do mesmo estado, a sessão mais antiga vem primeiro.
O botão "Ir para" foca a primeira sessão se o estado dela for `waiting`, `error` ou `done`.
