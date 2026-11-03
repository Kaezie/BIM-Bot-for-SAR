#pragma once

#include <stdint.h>
#include <string.h>

// Keep lease arithmetic independent of the board so rollover and renewal can
// be checked without a camera. Unsigned subtraction survives millis() wrap.
struct IlluminationLease {
  static constexpr uint32_t durationMs = 15000;
  bool enabled = false;
  uint32_t renewedAt = 0;

  void set(bool requested, uint32_t now) {
    enabled = requested;
    renewedAt = now;
  }

  bool expire(uint32_t now, bool connected) {
    if (enabled && (!connected || uint32_t(now - renewedAt) >= durationMs)) {
      enabled = false;
      return true;
    }
    return false;
  }
};

// Accept a single exact key/value; reject duplicates, unknown parameters,
// malformed values and encoded alternatives instead of interpreting loosely.
inline bool parseLightQuery(const char *query, bool &enabled) {
  if (strcmp(query, "enabled=1") == 0) { enabled = true; return true; }
  if (strcmp(query, "enabled=0") == 0) { enabled = false; return true; }
  return false;
}
