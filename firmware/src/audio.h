// Alerta sonoro: codec ES8311 (I2C 0x18) + I2S + amplificador (GPIO46) do ESP32-S3-BOX.
#pragma once
#include <stdint.h>

namespace audio {
// Chamar depois de lcd.init(): reaproveita o I2C do touch (porta 1, SDA 8 / SCL 18).
bool begin();
void chime();  // não bloqueia: toca numa task própria
void setMuted(bool m);
bool muted();
}  // namespace audio
