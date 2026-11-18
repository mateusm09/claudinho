// Modelo de sessões recebido do host (ver docs/protocol.md)
#pragma once
#include <stdint.h>

enum State : uint8_t { ST_WAITING, ST_ERROR, ST_DONE, ST_WORKING, ST_IDLE, ST_COUNT };

struct SessionView {
  char id[64];
  char name[33];
  State state;
  uint32_t age;  // segundos no momento do snapshot
  char at[6];    // "HH:MM" em que ficou pronta/erro (vazio nos outros estados)
};

struct Model {
  static constexpr int MAX = 16;
  SessionView s[MAX];
  int n = 0;
  uint32_t seq = 0;
  uint32_t rxMillis = 0;  // millis() de quando o snapshot chegou
  bool haveSnap = false;
  // Uso da janela de 5h (opcional no snapshot)
  bool haveUsage = false;
  uint8_t usagePct = 0;
  uint32_t usageResetIn = 0;  // segundos até resetar, no momento do snapshot

  // ms desde o snapshot; 0 se nowMs for anterior a rxMillis (evita underflow em uint32)
  uint32_t sinceRx(uint32_t nowMs) const {
    int32_t d = (int32_t)(nowMs - rxMillis);
    return d > 0 ? (uint32_t)d : 0;
  }
  uint32_t ageNow(int i, uint32_t nowMs) const { return s[i].age + sinceRx(nowMs) / 1000; }
  uint32_t resetInNow(uint32_t nowMs) const {
    uint32_t el = sinceRx(nowMs) / 1000;
    return el < usageResetIn ? usageResetIn - el : 0;
  }
  bool hostAlive(uint32_t nowMs) const { return haveSnap && sinceRx(nowMs) < 90000; }
  // Sessão alvo do botão "Ir para": a primeira se for acionável (lista já vem ordenada)
  int target() const { return (n > 0 && s[0].state <= ST_DONE) ? 0 : -1; }
};

State parseState(const char *str);
