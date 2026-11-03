#pragma once
#include <atomic>
#include <stdint.h>

// Rejoin the robot hotspot soon after an attempt reports failure. At power-on
// this camera usually looks for the hotspot before the original camera has
// started it; waiting 30 s after each failed attempt kept Night offline long
// after the hotspot returned. An attempt that reports nothing is still never
// interrupted before the 30 s stall limit.
class WifiRetry {
 public:
  static constexpr uint32_t failedRetryMs = 3000;
  static constexpr uint32_t stalledRetryMs = 30000;

  void attempted(uint32_t now) {
    attemptedAt_ = now;
    failed_.store(false);
  }

  // Called from the Wi-Fi event task when the current attempt reports failure.
  void failed() { failed_.store(true); }

  bool due(uint32_t now) const {
    return uint32_t(now - attemptedAt_) >= (failed_.load() ? failedRetryMs : stalledRetryMs);
  }

 private:
  uint32_t attemptedAt_ = 0;
  std::atomic<bool> failed_{false};
};
