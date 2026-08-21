#pragma once

#include "esphome/core/application.h"
#include "esphome/core/component.h"
#include "esphome/core/log.h"
#include "esphome/components/esp8266/preferences.h"

#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <string>

extern "C" {
#include <spi_flash.h>
#include <user_interface.h>
}

namespace esphome::ct30w_stock_ota {

class CT30WStockOTA final : public Component {
 public:
  bool start(const std::string &url) {
    if (this->pending_ || this->busy_ || url.rfind("http://", 0) != 0) {
      return false;
    }
    this->url_ = url;
    this->pending_ = true;
    return true;
  }

  void loop() override {
    if (!this->pending_ || this->busy_) {
      return;
    }
    this->pending_ = false;
    this->busy_ = true;
    const bool ok = this->run_();
    this->busy_ = false;
    this->url_.clear();
    if (!ok) {
      ESP_LOGE(TAG, "Stock-compatible OTA failed; COPY_HEADER remains uncommitted");
      return;
    }
    ESP_LOGI(TAG, "Stock-compatible OTA committed; rebooting through stock bootloader");
    this->set_timeout("stock_ota_reboot", 500, []() { App.reboot(); });
  }

  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

 protected:
  static constexpr const char *TAG = "ct30w.stock_ota";
  static constexpr uint32_t METADATA_SIZE = 0x24;
  static constexpr uint32_t COPY_HEADER_OFFSET = 0x100000;
  static constexpr uint32_t STAGING_OFFSET = 0x101000;
  static constexpr uint32_t STAGING_SIZE = 0xFA000;
  static constexpr uint32_t SECTOR_SIZE = 0x1000;
  static constexpr size_t BUFFER_SIZE = 1024;
  static constexpr uint32_t IO_TIMEOUT_MS = 15000;

  static uint32_t read_le32_(const uint8_t *data) {
    return static_cast<uint32_t>(data[0]) | (static_cast<uint32_t>(data[1]) << 8) |
           (static_cast<uint32_t>(data[2]) << 16) | (static_cast<uint32_t>(data[3]) << 24);
  }

  static uint32_t crc32_update_(uint32_t crc, const uint8_t *data, size_t len) {
    while (len-- != 0) {
      crc ^= *data++;
      for (uint8_t bit = 0; bit < 8; bit++) {
        crc = (crc >> 1) ^ ((crc & 1U) ? UINT32_C(0xEDB88320) : 0U);
      }
    }
    return crc;
  }

  static bool read_exact_(WiFiClient &stream, uint8_t *output, size_t len) {
    size_t done = 0;
    uint32_t last_progress = millis();
    while (done < len) {
      const int available = stream.available();
      if (available > 0) {
        const size_t want = std::min(len - done, static_cast<size_t>(available));
        const int got = stream.read(output + done, want);
        if (got <= 0) {
          return false;
        }
        done += static_cast<size_t>(got);
        last_progress = millis();
        App.feed_wdt();
        continue;
      }
      if (!stream.connected() || millis() - last_progress > IO_TIMEOUT_MS) {
        return false;
      }
      delay(1);
    }
    return true;
  }

  static bool erase_sector_(uint32_t address) {
    App.feed_wdt();
    return spi_flash_erase_sector(address / SECTOR_SIZE) == SPI_FLASH_RESULT_OK;
  }

  static bool read_flash_(uint32_t address, uint8_t *output, size_t len) {
    return (address % 4U) == 0 && (len % 4U) == 0 &&
           spi_flash_read(address, reinterpret_cast<uint32_t *>(output), len) == SPI_FLASH_RESULT_OK;
  }

  static bool write_flash_(uint32_t address, const uint8_t *data, size_t len) {
    App.feed_wdt();
    return (address % 4U) == 0 && (len % 4U) == 0 &&
           spi_flash_write(address, reinterpret_cast<uint32_t *>(const_cast<uint8_t *>(data)), len) ==
               SPI_FLASH_RESULT_OK;
  }

  static bool erase_control_header_() {
    if (!erase_sector_(COPY_HEADER_OFFSET)) {
      return false;
    }
    alignas(4) std::array<uint8_t, 8> header{};
    if (!read_flash_(COPY_HEADER_OFFSET, header.data(), header.size())) {
      return false;
    }
    return std::all_of(header.begin(), header.begin() + 6, [](uint8_t value) { return value == 0xFF; });
  }

  static bool erase_staging_(uint32_t body_size) {
    const uint32_t sectors = (body_size + SECTOR_SIZE - 1) / SECTOR_SIZE;
    for (uint32_t index = 0; index < sectors; index++) {
      if (!erase_sector_(STAGING_OFFSET + index * SECTOR_SIZE)) {
        return false;
      }
    }
    return true;
  }

  static bool verify_staging_crc_(uint32_t body_size, uint32_t expected_crc) {
    alignas(4) std::array<uint8_t, BUFFER_SIZE> buffer{};
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    uint32_t offset = 0;
    while (offset < body_size) {
      const size_t chunk = std::min(static_cast<uint32_t>(buffer.size()), body_size - offset);
      if (!read_flash_(STAGING_OFFSET + offset, buffer.data(), chunk)) {
        return false;
      }
      crc = crc32_update_(crc, buffer.data(), chunk);
      offset += chunk;
      App.feed_wdt();
    }
    return (crc ^ UINT32_C(0xFFFFFFFF)) == expected_crc;
  }

  static bool commit_control_header_(uint32_t body_size) {
    alignas(4) std::array<uint8_t, 8> header;
    header.fill(0xFF);
    header[0] = 0x01;
    header[1] = 0x00;
    header[2] = static_cast<uint8_t>(body_size);
    header[3] = static_cast<uint8_t>(body_size >> 8);
    header[4] = static_cast<uint8_t>(body_size >> 16);
    header[5] = static_cast<uint8_t>(body_size >> 24);
    if (!write_flash_(COPY_HEADER_OFFSET, header.data(), header.size())) {
      return false;
    }
    alignas(4) std::array<uint8_t, 8> check{};
    return read_flash_(COPY_HEADER_OFFSET, check.data(), check.size()) &&
           std::equal(header.begin(), header.begin() + 6, check.begin());
  }

  bool run_() {
    WiFiClient client;
    HTTPClient http;
    http.setTimeout(IO_TIMEOUT_MS);
    http.useHTTP10(true);
    if (!http.begin(client, this->url_.c_str())) {
      ESP_LOGE(TAG, "HTTP begin failed");
      return false;
    }
    const int response = http.GET();
    if (response != HTTP_CODE_OK) {
      ESP_LOGE(TAG, "HTTP status %d", response);
      http.end();
      return false;
    }

    WiFiClient *stream = http.getStreamPtr();
    alignas(4) std::array<uint8_t, METADATA_SIZE> metadata{};
    if (stream == nullptr || !read_exact_(*stream, metadata.data(), metadata.size())) {
      ESP_LOGE(TAG, "Short OTA metadata");
      http.end();
      return false;
    }

    const uint32_t body_size = read_le32_(metadata.data());
    const uint32_t expected_crc = read_le32_(metadata.data() + 4);
    const uint32_t fin_flag = read_le32_(metadata.data() + 8);
    const int content_length = http.getSize();
    const bool metadata_ok = body_size > 0 && body_size <= STAGING_SIZE && (body_size % 4U) == 0 &&
                             fin_flag == 1 && std::memcmp(metadata.data() + 12, "CT30\0", 5) == 0 &&
                             content_length == static_cast<int>(METADATA_SIZE + body_size);
    if (!metadata_ok) {
      ESP_LOGE(TAG, "Rejected OTA metadata");
      http.end();
      return false;
    }

    esp8266::preferences_prevent_write(true);
    wifi_set_sleep_type(NONE_SLEEP_T);
    if (!erase_control_header_()) {
      ESP_LOGE(TAG, "Could not establish erased COPY_HEADER");
      esp8266::preferences_prevent_write(false);
      http.end();
      return false;
    }
    if (!erase_staging_(body_size)) {
      ESP_LOGE(TAG, "Could not erase staging");
      esp8266::preferences_prevent_write(false);
      http.end();
      return false;
    }

    alignas(4) std::array<uint8_t, BUFFER_SIZE> buffer{};
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    uint32_t received = 0;
    while (received < body_size) {
      const size_t chunk = std::min(static_cast<uint32_t>(buffer.size()), body_size - received);
      if (!read_exact_(*stream, buffer.data(), chunk)) {
        ESP_LOGE(TAG, "Short OTA body at %u", received);
        esp8266::preferences_prevent_write(false);
        http.end();
        return false;
      }
      crc = crc32_update_(crc, buffer.data(), chunk);
      if (!write_flash_(STAGING_OFFSET + received, buffer.data(), chunk)) {
        ESP_LOGE(TAG, "Staging write failed at 0x%06X", STAGING_OFFSET + received);
        esp8266::preferences_prevent_write(false);
        http.end();
        return false;
      }
      received += chunk;
    }
    http.end();

    const uint32_t actual_crc = crc ^ UINT32_C(0xFFFFFFFF);
    if (actual_crc != expected_crc || !verify_staging_crc_(body_size, expected_crc)) {
      ESP_LOGE(TAG, "OTA CRC/readback verification failed");
      esp8266::preferences_prevent_write(false);
      return false;
    }
    if (!commit_control_header_(body_size)) {
      ESP_LOGE(TAG, "COPY_HEADER commit failed");
      esp8266::preferences_prevent_write(false);
      return false;
    }
    esp8266::preferences_prevent_write(false);
    return true;
  }

  std::string url_;
  bool pending_{false};
  bool busy_{false};
};

}  // namespace esphome::ct30w_stock_ota
