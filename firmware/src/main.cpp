// Claudinho — firmware do ESP32-S3-BOX
#include <ArduinoJson.h>

#include "audio.h"
#include "board.h"
#include "model.h"
#include "ui.h"

static constexpr const char *FW_VERSION = "0.6.0";
static constexpr int BTN_IDX = 1000;  // mesmo valor de ui.cpp

static LGFX lcd;
static Model model;
static char lineBuf[4096];
static size_t lineLen = 0;
static bool lineOverflow = false;
static bool dirty = true;
static uint32_t rerenderAt = 0;  // redesenho agendado (fim do destaque de toque)

State parseState(const char *str) {
  static const char *names[ST_COUNT] = {"waiting", "error", "done", "working", "idle"};
  for (int i = 0; i < ST_COUNT; i++)
    if (str && strcmp(str, names[i]) == 0) return (State)i;
  return ST_IDLE;
}

static void handleLine(const char *line) {
  JsonDocument doc;
  if (deserializeJson(doc, line)) return;  // lixo / JSON inválido: ignora
  JsonObject snap = doc["snap"];
  if (snap.isNull()) return;
  JsonArray arr = snap["sessions"];
  Model next;
  for (JsonObject o : arr) {
    if (next.n >= Model::MAX) break;
    SessionView &s = next.s[next.n++];
    strlcpy(s.id, o["id"] | "", sizeof s.id);
    strlcpy(s.name, o["name"] | "?", sizeof s.name);
    s.state = parseState(o["state"] | "idle");
    s.age = o["age"] | 0;
    strlcpy(s.at, o["at"] | "", sizeof s.at);
  }
  next.seq = snap["seq"] | 0;
  next.rxMillis = millis();
  next.haveSnap = true;
  // Alerta só quando uma sessão ENTRA em "esperando" (não no 1º snapshot após o boot).
  bool newWaiting = false;
  if (model.haveSnap) {
    for (int i = 0; i < next.n && !newWaiting; i++) {
      if (next.s[i].state != ST_WAITING) continue;
      bool was = false;
      for (int j = 0; j < model.n; j++)
        if (model.s[j].state == ST_WAITING && strcmp(model.s[j].id, next.s[i].id) == 0) was = true;
      newWaiting = !was;
    }
  }
  model = next;
  if (newWaiting) {
    audio::chime();
    ui::flashBorder(millis() + 1500);
  }
  dirty = true;
  Serial.printf("{\"ack\":%u}\n", (unsigned)model.seq);
}

static void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!lineOverflow && lineLen > 0) {
        lineBuf[lineLen] = 0;
        handleLine(lineBuf);
      }
      lineLen = 0;
      lineOverflow = false;
    } else if (c != '\r') {
      if (lineLen < sizeof lineBuf - 1) lineBuf[lineLen++] = c;
      else lineOverflow = true;  // linha grande demais: descarta até o próximo \n
    }
  }
}

// Esconde a linha na hora (o host confirma no próximo snapshot) e avisa o host.
static void hideSession(int idx) {
  if (idx < 0 || idx >= model.n) return;
  JsonDocument doc;
  doc["hide"] = model.s[idx].id;
  serializeJson(doc, Serial);
  Serial.print('\n');
  for (int j = idx; j < model.n - 1; j++) model.s[j] = model.s[j + 1];
  model.n--;
}

static void sendFocus(int idx) {
  if (idx == BTN_IDX) idx = model.target();
  if (idx < 0 || idx >= model.n) return;
  JsonDocument doc;
  doc["focus"] = model.s[idx].id;
  serializeJson(doc, Serial);
  Serial.print('\n');
}

static void pollTouch(uint32_t now) {
  static bool wasDown = false;
  lgfx::touch_point_t tp;
  bool down = lcd.getTouch(&tp) > 0;
  if (down && !wasDown) {
    int hit = ui::hitTest(model, tp.x, tp.y);
    if (hit == ui::HIT_HEADER) {
      audio::setMuted(!audio::muted());
      ui::setMutedIcon(audio::muted());
      if (!audio::muted()) audio::chime();  // amostra ao religar
      dirty = true;
    } else if (hit >= ui::HIT_HIDE) {
      hideSession(hit - ui::HIT_HIDE);
      dirty = true;
    } else if (hit >= 0) {
      ui::setPressed(hit, now + 250);
      rerenderAt = now + 260;
      sendFocus(hit);
      dirty = true;
    }
  }
  wasDown = down;
}

void setup() {
  // Folga para vários snapshots seguidos: se o buffer RX do HWCDC estoura
  // (ex.: durante o pushSprite de ~30 ms), o core 2.0.x para de receber até
  // reabrir a porta. O host limita cada linha a 4 KB (docs/protocol.md).
  Serial.setRxBufferSize(16384);
  Serial.begin(115200);
  lcd.init();
  lcd.setRotation(1);
  float affine[6] = {1, 0, 0, 0, -1, 240};  // TT21100 do S3-BOX tem Y invertido
  lcd.getPanel()->setCalibrateAffine(affine);
  lcd.setBrightness(160);
  ui::begin(lcd);
  bool audioOk = audio::begin();
  ui::setMutedIcon(audio::muted());
  Serial.printf("{\"log\":\"audio %s\"}\n", audioOk ? "ok" : "falhou");
}

void loop() {
  pollSerial();
  uint32_t now = millis();  // depois da serial: rxMillis nunca fica no "futuro"
  pollTouch(now);

  static uint32_t lastHello = 0;
  if (!model.hostAlive(now) && now - lastHello > 2000) {
    lastHello = now;
    Serial.printf("{\"hello\":1,\"board\":\"ESP32-S3-BOX\",\"fw\":\"%s\"}\n", FW_VERSION);
  }

  static uint32_t lastRender = 0;
  static bool wasAlive = false;
  bool alive = model.hostAlive(now);
  bool scheduled = rerenderAt && (int32_t)(now - rerenderAt) >= 0;
  if (scheduled) rerenderAt = 0;
  if (dirty || scheduled || alive != wasAlive || ui::animDue(model, now) || now - lastRender > 1000) {
    ui::render(model, now);
    lastRender = now;
    dirty = false;
    wasAlive = alive;
  }
  delay(5);
}
