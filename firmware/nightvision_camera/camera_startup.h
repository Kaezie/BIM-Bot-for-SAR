#pragma once
#include <stdint.h>

// A failed sensor probe must not strand setup() before Wi-Fi can connect.
// Measure each cooldown from completion, even when initialization is slow.
class CameraStartup {
 public:
  static constexpr uint32_t settleMs = 500;
  static constexpr uint32_t retryMs = 3000;

  void begin(uint32_t now) {
    lastCompletedAt_ = now;
    attempted_ = false;
    ready_ = false;
  }

  bool due(uint32_t now) const {
    return !ready_ && uint32_t(now - lastCompletedAt_) >= (attempted_ ? retryMs : settleMs);
  }

  void complete(uint32_t now, bool success) {
    lastCompletedAt_ = now;
    attempted_ = true;
    ready_ = success;
  }

 private:
  uint32_t lastCompletedAt_ = 0;
  bool attempted_ = false;
  bool ready_ = false;
};
