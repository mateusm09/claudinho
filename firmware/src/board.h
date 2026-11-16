// Configuração explícita do ESP32-S3-BOX (original): ILI9342C + TT21100.
// O autodetect do LovyanGFX cai no BOX-3 por padrão com -DARDUINO_ESP32_S3_BOX
// (backlight no GPIO47 → tela preta), por isso configuramos à mão.
#pragma once
#include <LovyanGFX.hpp>

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9342 _panel;
  lgfx::Bus_SPI _bus;
  lgfx::Light_PWM _light;
  lgfx::Touch_TT21xxx _touch;

 public:
  LGFX() {
    {
      auto c = _bus.config();
      c.spi_host = SPI2_HOST;
      c.spi_mode = 0;
      c.freq_write = 40000000;
      c.freq_read = 16000000;
      c.spi_3wire = true;
      c.use_lock = true;
      c.dma_channel = SPI_DMA_CH_AUTO;
      c.pin_sclk = 7;
      c.pin_mosi = 6;
      c.pin_miso = -1;
      c.pin_dc = 4;
      _bus.config(c);
      _panel.setBus(&_bus);
    }
    {
      auto c = _panel.config();
      c.pin_cs = 5;
      c.pin_rst = 48;
      c.pin_busy = -1;
      c.panel_width = 320;
      c.panel_height = 240;
      c.offset_rotation = 1;
      c.readable = false;
      c.invert = false;
      c.rgb_order = false;
      c.bus_shared = false;
      _panel.config(c);
    }
    {
      auto c = _light.config();
      c.pin_bl = 45;
      c.invert = false;
      c.freq = 12000;
      c.pwm_channel = 0;
      _light.config(c);
      _panel.setLight(&_light);
    }
    {
      auto c = _touch.config();
      c.pin_int = 3;
      c.pin_sda = 8;
      c.pin_scl = 18;
      c.i2c_addr = 0x24;
      c.i2c_port = 1;
      c.freq = 400000;
      c.x_min = 0;
      c.x_max = 319;
      c.y_min = 0;
      c.y_max = 239;
      c.bus_shared = false;
      _touch.config(c);
      _panel.setTouch(&_touch);
    }
    setPanel(&_panel);
  }
};
