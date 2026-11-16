#include "ui.h"

#include <string.h>

#include "mascot.h"

namespace {
LGFX *g_lcd;
LGFX_Sprite g_fb;  // framebuffer em PSRAM (320x240x16bpp = 150 KB)
int g_pressed = -1;
uint32_t g_pressedUntil = 0;
uint32_t g_flashUntil = 0;
bool g_mutedIcon = false;
constexpr uint32_t FLASH_PHASE_MS = 250;

constexpr int W = 320, H = 240;
constexpr int HEADER_H = 38;
constexpr int ROW_Y0 = 42, ROW_H = 36, ROW_GAP = 4, VISIBLE_ROWS = 4;
constexpr int BTN_Y = 198, BTN_H = 38;
constexpr int BTN_IDX = 1000;  // marcador interno de "botão pressionado"
constexpr int HIDE_W = 36;     // zona de toque do ícone "esconder", na ponta direita da linha
constexpr int HIDE_X = W - 6 - HIDE_W;

uint32_t rgb(uint32_t hex) { return lgfx::color888(hex >> 16, (hex >> 8) & 0xFF, hex & 0xFF); }

const uint32_t C_BG = 0x141414, C_ROW = 0x242424, C_ROW_HI = 0x3A3A3A, C_TEXT = 0xECECEC,
               C_MUTED = 0x8B8D98, C_CLAUDE = 0xD97757;
const uint32_t C_STATE[ST_COUNT] = {0xF5A623, 0xE5484D, 0x30A46C, 0x3E9BFF, 0x6B6E78};
const char *L_STATE[ST_COUNT] = {"esperando", "erro", "pronto", "trabalhando", "ocioso"};

void fmtAge(uint32_t s, char *out, size_t n) {
  if (s < 60) snprintf(out, n, "%us", (unsigned)s);
  else if (s < 3600) snprintf(out, n, "%um", (unsigned)(s / 60));
  else if (s < 86400) snprintf(out, n, "%uh", (unsigned)(s / 3600));
  else snprintf(out, n, "%ud", (unsigned)(s / 86400));
}

// Desenha texto cortando com ".." se passar de maxW.
void drawFit(const char *txt, int x, int y, int maxW) {
  char buf[48];
  strncpy(buf, txt, sizeof buf - 1);
  buf[sizeof buf - 1] = 0;
  if (g_fb.textWidth(buf) > maxW) {
    size_t len = strlen(buf);
    while (len > 1) {
      buf[--len] = 0;
      char tmp[52];
      snprintf(tmp, sizeof tmp, "%s..", buf);
      if (g_fb.textWidth(tmp) <= maxW) { strcpy(buf, tmp); break; }
    }
  }
  g_fb.drawString(buf, x, y);
}

mascot::Anim animFor(const Model &m, uint32_t nowMs) {
  if (!m.hostAlive(nowMs)) return mascot::A_SLEEP;
  if (m.n == 0) return mascot::A_IDLE;
  switch (m.s[0].state) {  // lista já vem ordenada por prioridade
    case ST_WAITING: return mascot::A_WAITING;
    case ST_ERROR:   return mascot::A_ERROR;
    case ST_DONE:    return mascot::A_DONE;
    case ST_WORKING: return mascot::A_WORKING;
    default:         return mascot::A_IDLE;
  }
}

int frameIndex(mascot::Anim a, uint32_t nowMs) {
  const auto &info = mascot::ANIMS[a];
  return info.first + (nowMs / info.ms) % info.count;
}

int g_lastFrame = -1;  // último quadro desenhado (para saber quando redesenhar)

void drawMascot(int x, int y, int scale, int frame) {
  static uint16_t pal[sizeof(mascot::PALETTE) / sizeof(mascot::PALETTE[0])];
  static bool palReady = false;
  if (!palReady) {
    for (size_t i = 0; i < sizeof(pal) / sizeof(pal[0]); i++) {
      uint32_t c = mascot::PALETTE[i];
      pal[i] = lgfx::color565(c >> 16, (c >> 8) & 0xFF, c & 0xFF);
    }
    palReady = true;
  }
  const auto &f = mascot::FRAMES[frame];
  for (int py = 0; py < mascot::H; py++)
    for (int px = 0; px < mascot::W; px++)
      if (uint8_t v = f[py][px]) g_fb.fillRect(x + px * scale, y + py * scale, scale, scale, pal[v]);
}

void drawHeader(const Model &m, int frame, bool bigMascot) {
  if (!bigMascot) drawMascot(4, 5, 2, frame);
  g_fb.setFont(&fonts::FreeSansBold12pt7b);
  g_fb.setTextDatum(textdatum_t::middle_left);
  g_fb.setTextColor(rgb(C_CLAUDE));
  g_fb.drawString("Claudinho", bigMascot ? 10 : 44, HEADER_H / 2);

  if (g_mutedIcon) {  // alto-falante riscado, à direita do título
    int x0 = (bigMascot ? 10 : 44) + g_fb.textWidth("Claudinho") + 8, y0 = HEADER_H / 2;
    uint32_t c = rgb(C_MUTED);
    g_fb.fillRect(x0, y0 - 3, 4, 6, c);
    g_fb.fillTriangle(x0 + 3, y0, x0 + 9, y0 - 6, x0 + 9, y0 + 6, c);
    g_fb.drawLine(x0 - 1, y0 + 7, x0 + 11, y0 - 7, rgb(C_STATE[ST_ERROR]));
  }

  int counts[ST_COUNT] = {};
  for (int i = 0; i < m.n; i++) counts[m.s[i].state]++;
  g_fb.setFont(&fonts::FreeSansBold9pt7b);
  g_fb.setTextDatum(textdatum_t::middle_right);
  int x = W - 8;
  const State shown[] = {ST_DONE, ST_ERROR, ST_WAITING};  // da direita para a esquerda
  for (State st : shown) {
    if (!counts[st]) continue;
    char b[8];
    snprintf(b, sizeof b, "%d", counts[st]);
    g_fb.setTextColor(rgb(C_STATE[st]));
    g_fb.drawString(b, x, HEADER_H / 2);
    x -= g_fb.textWidth(b) + 4;
    g_fb.fillCircle(x - 4, HEADER_H / 2, 4, rgb(C_STATE[st]));
    x -= 16;
  }
}

// Olho riscado ("esconder"), centrado em (cx, cy).
void drawHideIcon(int cx, int cy, uint32_t c) {
  g_fb.drawEllipse(cx, cy, 7, 4, c);
  g_fb.fillCircle(cx, cy, 2, c);
  g_fb.drawLine(cx - 7, cy + 6, cx + 7, cy - 6, c);
  g_fb.drawLine(cx - 6, cy + 6, cx + 8, cy - 6, c);
}

void drawRow(const Model &m, int i, int y, uint32_t nowMs) {
  const SessionView &s = m.s[i];
  bool pressed = nowMs < g_pressedUntil && (g_pressed == i || (g_pressed == BTN_IDX && i == m.target()));
  g_fb.fillRoundRect(6, y, W - 12, ROW_H, 6, rgb(pressed ? C_ROW_HI : C_ROW));
  g_fb.fillRoundRect(6, y, 6, ROW_H, 3, rgb(C_STATE[s.state]));

  // zona "esconder": separador fino + ícone (a linha some na hora ao tocar)
  g_fb.drawFastVLine(HIDE_X, y + 8, ROW_H - 16, rgb(0x3A3A3A));
  drawHideIcon(HIDE_X + HIDE_W / 2, y + ROW_H / 2, rgb(C_MUTED));

  int right = HIDE_X - 8;
  char age[8];
  if (s.at[0]) strlcpy(age, s.at, sizeof age);  // pronto/erro: horário fixo, não conta
  else fmtAge(m.ageNow(i, nowMs), age, sizeof age);
  g_fb.setFont(&fonts::Font2);
  g_fb.setTextDatum(textdatum_t::middle_right);
  g_fb.setTextColor(rgb(C_MUTED));
  g_fb.drawString(age, right, y + ROW_H / 2);
  int ageW = g_fb.textWidth(age);
  g_fb.setTextColor(rgb(C_STATE[s.state]));
  g_fb.drawString(L_STATE[s.state], right - ageW - 8, y + ROW_H / 2);
  int labelW = g_fb.textWidth(L_STATE[s.state]);

  g_fb.setFont(&fonts::FreeSans9pt7b);
  g_fb.setTextDatum(textdatum_t::middle_left);
  g_fb.setTextColor(rgb(C_TEXT));
  drawFit(s.name, 20, y + ROW_H / 2, right - ageW - 8 - labelW - 10 - 20);
}

void drawButton(const Model &m, uint32_t nowMs) {
  int t = m.target();
  bool pressed = g_pressed == BTN_IDX && nowMs < g_pressedUntil;
  g_fb.setTextDatum(textdatum_t::middle_center);
  if (t < 0) {
    g_fb.drawRoundRect(6, BTN_Y, W - 12, BTN_H, 8, rgb(0x333333));
    g_fb.setFont(&fonts::Font2);
    g_fb.setTextColor(rgb(C_MUTED));
    g_fb.drawString("nada pedindo atencao", W / 2, BTN_Y + BTN_H / 2);
    return;
  }
  uint32_t c = C_STATE[m.s[t].state];
  g_fb.fillRoundRect(6, BTN_Y, W - 12, BTN_H, 8, pressed ? rgb(0xFFFFFF) : rgb(c));
  g_fb.setFont(&fonts::FreeSansBold9pt7b);
  g_fb.setTextColor(rgb(0x141414));
  char b[48];
  snprintf(b, sizeof b, "Ir para %s", m.s[t].name);
  g_fb.setTextDatum(textdatum_t::middle_left);
  int w = std::min<int>(g_fb.textWidth(b), W - 40);
  drawFit(b, W / 2 - w / 2, BTN_Y + BTN_H / 2, W - 40);
}

void drawCentered(const char *msg, const char *sub, int frame) {
  constexpr int S = 7;  // mascote grande: 112x98
  drawMascot(W / 2 - mascot::W * S / 2, 36, S, frame);
  g_fb.setTextDatum(textdatum_t::middle_center);
  g_fb.setFont(&fonts::FreeSans9pt7b);
  g_fb.setTextColor(rgb(C_TEXT));
  g_fb.drawString(msg, W / 2, 150);
  if (sub) {
    g_fb.setFont(&fonts::Font2);
    g_fb.setTextColor(rgb(C_MUTED));
    g_fb.drawString(sub, W / 2, 172);
  }
}
}  // namespace

namespace ui {
void begin(LGFX &lcd) {
  g_lcd = &lcd;
  g_fb.setPsram(true);
  g_fb.setColorDepth(16);
  g_fb.createSprite(W, H);
}

void render(const Model &m, uint32_t nowMs) {
  int frame = frameIndex(animFor(m, nowMs), nowMs);
  g_lastFrame = frame;
  bool big = !m.hostAlive(nowMs) || m.n == 0;
  g_fb.fillScreen(rgb(C_BG));
  drawHeader(m, frame, big);
  if (!m.hostAlive(nowMs)) {
    drawCentered("Aguardando o Mac...", "rode o claudinhod", frame);
  } else if (m.n == 0) {
    drawCentered("Nenhuma sessao ativa", "tudo tranquilo por aqui", frame);
  } else {
    int rows = std::min(m.n, VISIBLE_ROWS);
    for (int i = 0; i < rows; i++) drawRow(m, i, ROW_Y0 + i * (ROW_H + ROW_GAP), nowMs);
    if (m.n > VISIBLE_ROWS) {
      char b[16];
      snprintf(b, sizeof b, "+%d", m.n - VISIBLE_ROWS);
      g_fb.setFont(&fonts::Font2);
      g_fb.setTextDatum(textdatum_t::bottom_right);
      g_fb.setTextColor(rgb(C_MUTED));
      g_fb.drawString(b, W - 8, BTN_Y - 1);
    }
  }
  drawButton(m, nowMs);
  if (nowMs < g_flashUntil && (g_flashUntil - nowMs) / FLASH_PHASE_MS % 2 == 0) {
    for (int i = 0; i < 4; i++) g_fb.drawRoundRect(i, i, W - 2 * i, H - 2 * i, 8, rgb(C_STATE[ST_WAITING]));
  }
  g_fb.pushSprite(g_lcd, 0, 0);
}

uint32_t g_lastFlashPhase = 0;

bool animDue(const Model &m, uint32_t nowMs) {
  uint32_t phase = nowMs < g_flashUntil ? 1 + (g_flashUntil - nowMs) / FLASH_PHASE_MS : 0;
  bool flashChanged = phase != g_lastFlashPhase;
  g_lastFlashPhase = phase;
  return flashChanged || frameIndex(animFor(m, nowMs), nowMs) != g_lastFrame;
}

void flashBorder(uint32_t untilMs) { g_flashUntil = untilMs; }
void setMutedIcon(bool muted) { g_mutedIcon = muted; }

int hitTest(const Model &m, int x, int y) {
  if (y < HEADER_H) return HIT_HEADER;  // liga/desliga o som (funciona mesmo sem host)
  if (!m.hostAlive(millis())) return -1;
  if (y >= BTN_Y && y < BTN_Y + BTN_H) return m.target() >= 0 ? BTN_IDX : -1;
  if (y >= ROW_Y0 && y < BTN_Y) {
    int i = (y - ROW_Y0) / (ROW_H + ROW_GAP);
    int within = (y - ROW_Y0) % (ROW_H + ROW_GAP);
    if (within < ROW_H && i < std::min(m.n, VISIBLE_ROWS)) return x >= HIDE_X ? HIT_HIDE + i : i;
  }
  return -1;
}

void setPressed(int idx, uint32_t untilMs) {
  g_pressed = idx;
  g_pressedUntil = untilMs;
}
}  // namespace ui
