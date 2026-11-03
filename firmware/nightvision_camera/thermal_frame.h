#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

// A full image is published only after BOTH MLX90640 subpages are acquired.
// Keep freshness/encoding independent of Arduino for hardware-free checks.
struct ThermalFrame {
  static constexpr size_t rows = 24;
  static constexpr size_t columns = 32;
  static constexpr size_t pixels = rows * columns;
  static constexpr uint32_t maximumAgeMs = 5000;
  static constexpr size_t jsonCapacity = pixels * 8 + 512;

  float grid[pixels] = {};
  float minimum = 0;
  float maximum = 0;
  uint32_t capturedAt = 0;
  uint32_t sequence = 0;
  bool valid = false;

  void invalidate() { valid = false; }

  bool publish(const float *values, uint32_t now) {
    if (!values) { invalidate(); return false; }
    float low = 300, high = -40;
    for (size_t i = 0; i < pixels; ++i) {
      const float value = values[i];
      if (!std::isfinite(value) || value < -40 || value > 300) {
        invalidate();
        return false;
      }
      if (value < low) low = value;
      if (value > high) high = value;
    }
    std::memcpy(grid, values, sizeof(grid));
    minimum = low;
    maximum = high;
    capturedAt = now;
    if (++sequence == 0) ++sequence;
    valid = true;
    return true;
  }

  bool fresh(uint32_t now) const {
    return valid && uint32_t(now - capturedAt) < maximumAgeMs;
  }
};

// Encode a copied snapshot, never while holding the sensor-cache mutex. Capacity
// includes the terminator. Reject short buffers rather than send truncated JSON.
inline bool encodeThermalFrame(const ThermalFrame &frame, uint32_t now,
                               char *body, size_t capacity) {
  if (!body || capacity == 0) return false;
  body[0] = '\0';
  if (!frame.fresh(now)) return false;
  size_t used = 0;
  auto append = [&](const char *format, auto... values) {
    const int length = std::snprintf(body + used, capacity - used, format, values...);
    if (length < 0 || size_t(length) >= capacity - used) return false;
    used += size_t(length);
    return true;
  };
  if (!append("{\"sensor\":\"MLX90640\",\"fresh\":true,\"frame_age_ms\":%lu,"
              "\"sequence\":%lu,\"grid\":[", (unsigned long)(now - frame.capturedAt),
              (unsigned long)frame.sequence)) return false;
  for (size_t row = 0; row < ThermalFrame::rows; ++row) {
    if (!append("%s[", row ? "," : "")) return false;
    for (size_t col = 0; col < ThermalFrame::columns; ++col) {
      const float value = frame.grid[row * ThermalFrame::columns + col];
      if (!std::isfinite(value) || value < -40 || value > 300) return false;
      if (!append("%s%.2f", col ? "," : "", double(value))) return false;
    }
    if (!append("%s", "]")) return false;
  }
  return append("],\"min_temp\":%.2f,\"max_temp\":%.2f}",
                double(frame.minimum), double(frame.maximum));
}
