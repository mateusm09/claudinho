#include "audio.h"

#include <Arduino.h>
#include <LovyanGFX.hpp>
#include <Preferences.h>
#include <driver/i2s.h>
#include <math.h>

namespace {
constexpr int I2C_PORT = 1;  // mesmo do touch (board.h)
constexpr uint8_t ES8311 = 0x18;
constexpr uint32_t I2C_FREQ = 400000;
constexpr int PIN_MCLK = 2, PIN_BCLK = 17, PIN_LRCK = 47, PIN_DOUT = 15, PIN_PA = 46;
constexpr int RATE = 16000;
constexpr i2s_port_t I2S_PORT = I2S_NUM_0;

TaskHandle_t g_task = nullptr;
bool g_ok = false;
bool g_muted = false;

bool wr(uint8_t reg, uint8_t val) { return lgfx::i2c::writeRegister8(I2C_PORT, ES8311, reg, val, 0, I2C_FREQ).has_value(); }

bool codecInit() {
  // ES8311 como escravo, MCLK = 256 * 16 kHz = 4,096 MHz vindo do pino MCLK, I2S 16 bits, só DAC.
  const uint8_t seq[][2] = {
      {0x00, 0x1F}, {0x45, 0x00},                               // reset
      {0x00, 0x00}, {0x00, 0x80},                               // liga, modo escravo
      {0x01, 0x3F},                                             // clocks ligados, MCLK do pino
      {0x02, 0x00}, {0x03, 0x10}, {0x04, 0x10}, {0x05, 0x00},   // divisores p/ 4,096 MHz @ 16 kHz
      {0x06, 0x03}, {0x07, 0x00}, {0x08, 0xFF},
      {0x09, 0x0C}, {0x0A, 0x0C},                               // I2S, 16 bits
      {0x0B, 0x00}, {0x0C, 0x00}, {0x10, 0x1F}, {0x11, 0x7F},
      {0x0D, 0x01}, {0x0E, 0x02}, {0x12, 0x00}, {0x13, 0x10},   // analógico e DAC ligados, saída HP
      {0x1C, 0x6A}, {0x37, 0x08},                               // sem equalizador no DAC
      {0x32, 0xA8},                                             // volume (~ -11 dB)
      {0x31, 0x00},                                             // sem mudo
  };
  for (auto &rv : seq) {
    if (!wr(rv[0], rv[1])) return false;
    if (rv[0] == 0x00 && rv[1] == 0x1F) delay(20);
  }
  return true;
}

bool i2sInit() {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  cfg.sample_rate = RATE;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.dma_buf_count = 4;
  cfg.dma_buf_len = 256;
  cfg.tx_desc_auto_clear = true;  // silêncio quando não há dados (sem chiado)
  cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
  if (i2s_driver_install(I2S_PORT, &cfg, 0, nullptr) != ESP_OK) return false;
  i2s_pin_config_t pins = {};
  pins.mck_io_num = PIN_MCLK;
  pins.bck_io_num = PIN_BCLK;
  pins.ws_io_num = PIN_LRCK;
  pins.data_out_num = PIN_DOUT;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  return i2s_set_pin(I2S_PORT, &pins) == ESP_OK;
}

// Duas notas curtas (Mi6 → Si6) com envelope, para não estalar.
void playChime() {
  static int16_t buf[256 * 2];
  const struct { float hz; int ms; } notes[] = {{1318.5f, 90}, {0, 30}, {1975.5f, 140}};
  digitalWrite(PIN_PA, HIGH);
  for (auto &n : notes) {
    int total = RATE * n.ms / 1000;
    float phase = 0, step = 2 * PI * n.hz / RATE;
    for (int i = 0; i < total;) {
      int chunk = min(256, total - i);
      for (int k = 0; k < chunk; k++, i++) {
        float env = 1.0f;
        int attack = RATE / 200, release = RATE / 25;  // 5 ms / 40 ms
        if (i < attack) env = (float)i / attack;
        else if (total - i < release) env = (float)(total - i) / release;
        int16_t v = n.hz > 0 ? (int16_t)(sinf(phase) * 9000 * env) : 0;
        phase += step;
        buf[2 * k] = buf[2 * k + 1] = v;
      }
      size_t written;
      i2s_write(I2S_PORT, buf, chunk * 4, &written, portMAX_DELAY);
    }
  }
  delay(60);  // deixa o DMA esvaziar antes de desligar o amplificador
  digitalWrite(PIN_PA, LOW);
}

void task(void *) {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    playChime();
  }
}
}  // namespace

namespace audio {
bool begin() {
  Preferences p;
  p.begin("claudinho", true);
  g_muted = p.getBool("muted", false);
  p.end();
  pinMode(PIN_PA, OUTPUT);
  digitalWrite(PIN_PA, LOW);
  g_ok = i2sInit() && codecInit();
  if (g_ok) xTaskCreatePinnedToCore(task, "chime", 4096, nullptr, 1, &g_task, 1);
  return g_ok;
}

void chime() {
  if (g_ok && !g_muted && g_task) xTaskNotifyGive(g_task);
}

void setMuted(bool m) {
  g_muted = m;
  Preferences p;
  p.begin("claudinho", false);
  p.putBool("muted", m);
  p.end();
}

bool muted() { return g_muted; }
}  // namespace audio
