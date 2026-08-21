#pragma once

#include "esphome/components/esp8266/preferences.h"
#include "esphome/core/application.h"
#include "esphome/core/log.h"
#include "eboot_sector.h"

#include <Arduino.h>
#include <coredecls.h>
#include <eboot_command.h>
#include <spi_flash.h>
#include <user_interface.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>

namespace ct30w_eboot_migration {

static constexpr const char *TAG = "ct30w.eboot";
static constexpr uint32_t SECTOR_SIZE = 0x1000;
static constexpr uint32_t STAGING_MIN = 0x101000;
static constexpr uint32_t STAGING_END = 0x1FB000;
static constexpr size_t BUFFER_SIZE = 1024;

inline uint32_t crc32_update_(uint32_t crc, const uint8_t *data, size_t len) {
  while (len-- != 0) {
    crc ^= *data++;
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc >> 1) ^ ((crc & 1U) ? UINT32_C(0xEDB88320) : 0U);
    }
  }
  return crc;
}

inline bool parse_crc_(const std::string &text, uint32_t &output) {
  if (text.size() != 8) {
    return false;
  }
  uint32_t value = 0;
  for (char c : text) {
    uint8_t digit;
    if (c >= '0' && c <= '9') {
      digit = static_cast<uint8_t>(c - '0');
    } else if (c >= 'a' && c <= 'f') {
      digit = static_cast<uint8_t>(c - 'a' + 10);
    } else if (c >= 'A' && c <= 'F') {
      digit = static_cast<uint8_t>(c - 'A' + 10);
    } else {
      return false;
    }
    value = (value << 4) | digit;
  }
  output = value;
  return true;
}

inline bool read_flash_(uint32_t address, uint8_t *output, size_t len) {
  return (address % 4U) == 0 && (len % 4U) == 0 &&
         spi_flash_read(address, reinterpret_cast<uint32_t *>(output), len) == SPI_FLASH_RESULT_OK;
}

inline bool verify_flash_crc_(uint32_t address, uint32_t size, uint32_t expected_crc) {
  std::unique_ptr<uint8_t[]> buffer(new (std::nothrow) uint8_t[BUFFER_SIZE]);
  if (!buffer) {
    return false;
  }
  uint32_t crc = UINT32_C(0xFFFFFFFF);
  uint32_t offset = 0;
  while (offset < size) {
    const size_t chunk = std::min(static_cast<uint32_t>(BUFFER_SIZE), size - offset);
    if (!read_flash_(address + offset, buffer.get(), chunk)) {
      return false;
    }
    crc = crc32_update_(crc, buffer.get(), chunk);
    offset += chunk;
    App.feed_wdt();
  }
  return (crc ^ UINT32_C(0xFFFFFFFF)) == expected_crc;
}

inline bool normalize_staged_eboot_(uint32_t address, uint8_t *observed, const uint8_t *expected) {
  if (std::memcmp(observed, expected, SECTOR_SIZE) == 0) {
    return true;
  }
  if (std::memcmp(observed, expected, 2) != 0 ||
      std::memcmp(observed + 3, expected + 3, SECTOR_SIZE - 3) != 0) {
    return false;
  }
  ESP_LOGW(TAG, "normalizing OTA flash mode %02X -> %02X at 0x%06X", observed[2], expected[2], address);
  if (spi_flash_erase_sector(address / SECTOR_SIZE) != SPI_FLASH_RESULT_OK ||
      spi_flash_write(address, reinterpret_cast<uint32_t *>(const_cast<uint8_t *>(expected)), SECTOR_SIZE) !=
          SPI_FLASH_RESULT_OK ||
      !read_flash_(address, observed, SECTOR_SIZE)) {
    return false;
  }
  return std::memcmp(observed, expected, SECTOR_SIZE) == 0;
}

inline bool recover_staging_(uint32_t expected_size, uint32_t expected_crc, const uint8_t *expected_eboot,
                             uint32_t &source) {
  if (expected_size > STAGING_END - STAGING_MIN) {
    return false;
  }
  std::unique_ptr<uint8_t[]> sector(new (std::nothrow) uint8_t[SECTOR_SIZE]);
  alignas(4) std::array<uint8_t, 8> app_header{};
  if (!sector) {
    return false;
  }

  uint32_t matches = 0;
  const uint32_t last = STAGING_END - expected_size;
  for (uint32_t candidate = STAGING_MIN; candidate <= last; candidate += SECTOR_SIZE) {
    if (!read_flash_(candidate, sector.get(), SECTOR_SIZE) ||
        std::memcmp(sector.get(), expected_eboot, SECTOR_SIZE) != 0 ||
        !read_flash_(candidate + SECTOR_SIZE, app_header.data(), app_header.size()) || app_header[0] != 0xE9 ||
        app_header[2] != 0x03 || app_header[3] != 0x30 ||
        !verify_flash_crc_(candidate, expected_size, expected_crc)) {
      continue;
    }
    source = candidate;
    matches++;
  }
  if (matches != 1) {
    ESP_LOGE(TAG, "verified staging matches=%u", matches);
    return false;
  }
  return true;
}

inline bool installed_() {
  std::unique_ptr<uint8_t[]> observed(new (std::nothrow) uint8_t[SECTOR_SIZE]);
  std::unique_ptr<uint8_t[]> expected(new (std::nothrow) uint8_t[SECTOR_SIZE]);
  if (!observed || !expected || !read_flash_(0, observed.get(), SECTOR_SIZE)) {
    return false;
  }
  memcpy_P(expected.get(), CT30W_EBOOT_SECTOR, SECTOR_SIZE);
  return std::memcmp(observed.get(), expected.get(), SECTOR_SIZE) == 0;
}

inline void log_status() {
  ESP_LOGI(TAG, "bootloader=%s", installed_() ? "eboot" : "stock");
}

inline bool migrate(int32_t expected_size_signed, const std::string &expected_crc_text) {
  uint32_t expected_crc = 0;
  if (expected_size_signed <= static_cast<int32_t>(SECTOR_SIZE) ||
      !parse_crc_(expected_crc_text, expected_crc)) {
    ESP_LOGE(TAG, "invalid host confirmation");
    return false;
  }
  const uint32_t expected_size = static_cast<uint32_t>(expected_size_signed);

  eboot_command cmd{};
  const int command_read_result = eboot_command_read(&cmd);
  const bool command_usable = command_read_result == 0 && cmd.action == ACTION_COPY_RAW && cmd.args[1] == 0 &&
                              cmd.args[2] == expected_size && (cmd.args[0] % SECTOR_SIZE) == 0 &&
                              cmd.args[0] >= STAGING_MIN && cmd.args[0] + expected_size <= STAGING_END;

  std::unique_ptr<uint8_t[]> sector(new (std::nothrow) uint8_t[SECTOR_SIZE]);
  std::unique_ptr<uint8_t[]> expected(new (std::nothrow) uint8_t[SECTOR_SIZE]);
  alignas(4) std::array<uint8_t, 8> app_header{};
  if (!sector || !expected) {
    ESP_LOGE(TAG, "migration buffer allocation failed");
    return false;
  }
  memcpy_P(expected.get(), CT30W_EBOOT_SECTOR, SECTOR_SIZE);
  if (!command_usable) {
    ESP_LOGW(TAG, "RTC unusable read=%d magic=%08X action=%08X src=%08X dst=%08X size=%u", command_read_result,
             cmd.magic, static_cast<uint32_t>(cmd.action), cmd.args[0], cmd.args[1], cmd.args[2]);
    uint32_t recovered_source = 0;
    if (!recover_staging_(expected_size, expected_crc, expected.get(), recovered_source)) {
      ESP_LOGE(TAG, "RTC unusable and staged image recovery failed");
      return false;
    }
    cmd = {};
    cmd.action = ACTION_COPY_RAW;
    cmd.args[0] = recovered_source;
    cmd.args[1] = 0;
    cmd.args[2] = expected_size;
    ESP_LOGW(TAG, "recovered staging=0x%06X", recovered_source);
  }

  if (!read_flash_(cmd.args[0], sector.get(), SECTOR_SIZE) ||
      !read_flash_(cmd.args[0] + SECTOR_SIZE, app_header.data(), app_header.size())) {
    ESP_LOGE(TAG, "staged image read failed");
    return false;
  }
  if (!normalize_staged_eboot_(cmd.args[0], sector.get(), expected.get()) || app_header[0] != 0xE9 ||
      app_header[2] != 0x03 || app_header[3] != 0x30) {
    ESP_LOGE(TAG, "staged eboot/v1 image mismatch");
    return false;
  }
  if (!verify_flash_crc_(cmd.args[0], expected_size, expected_crc)) {
    ESP_LOGE(TAG, "staged image CRC mismatch");
    return false;
  }

  esphome::esp8266::preferences_prevent_write(true);
  wifi_set_sleep_type(NONE_SLEEP_T);
  eboot_command_write(&cmd);
  ESP_LOGI(TAG, "verified staging=0x%06X size=%u crc=%08X", cmd.args[0], expected_size, expected_crc);
  App.feed_wdt();
  if (spi_flash_erase_sector(0) != SPI_FLASH_RESULT_OK ||
      spi_flash_write(0, reinterpret_cast<uint32_t *>(expected.get()), SECTOR_SIZE) != SPI_FLASH_RESULT_OK) {
    ESP_LOGE(TAG, "sector0 write failed");
    esphome::esp8266::preferences_prevent_write(false);
    return false;
  }

  if (!read_flash_(0, sector.get(), SECTOR_SIZE) ||
      std::memcmp(sector.get(), expected.get(), SECTOR_SIZE) != 0) {
    ESP_LOGE(TAG, "sector0 readback mismatch");
    esphome::esp8266::preferences_prevent_write(false);
    return false;
  }

  ets_uart_printf("\nCT30_EBOOT:SECTOR0_VERIFIED\n");
  delay(250);
  ESP.restart();
  return true;
}

}  // namespace ct30w_eboot_migration

inline void ct30w_log_eboot_status() { ct30w_eboot_migration::log_status(); }
inline bool ct30w_migrate_eboot(int32_t expected_size, const std::string &expected_crc) {
  return ct30w_eboot_migration::migrate(expected_size, expected_crc);
}
