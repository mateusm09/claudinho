#pragma once
#include "board.h"
#include "model.h"

namespace ui {
void begin(LGFX &lcd);
void render(const Model &m, uint32_t nowMs);
// Retorna o índice da sessão tocada (linha ou botão), ou -1.
int hitTest(const Model &m, int x, int y);
void setPressed(int idx, uint32_t untilMs);
// True quando o quadro do mascote mudou desde o último render.
bool animDue(const Model &m, uint32_t nowMs);
// Borda piscando (âmbar) até untilMs: alerta de sessão nova esperando.
void flashBorder(uint32_t untilMs);
void setMutedIcon(bool muted);
constexpr int HIT_HEADER = 2000;  // retorno de hitTest para toque no cabeçalho
}  // namespace ui
