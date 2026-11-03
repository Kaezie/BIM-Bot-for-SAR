#pragma once

#include <stdint.h>
extern "C" {
#include "src/mlx90640/MLX90640_API.h"
}

// A single worker owns this instance and all sensor calls. HTTP handlers only
// read the separate validated snapshot; they must never call this driver.
class ThermalSensor {
 public:
  static constexpr int sdaPin = 14;
  static constexpr int sclPin = 13;
  static constexpr uint32_t operationTimeoutMs = 3000;
  enum Error {
    ok = 0,
    timeout = -100,
    notInitialized = -101,
    busUnavailable = -102,
    configurationMismatch = -103,
    invalidFrame = -104,
    unsupportedOperation = -105
  };

  bool begin();
  // Returns 0 only after two distinct, freshly acquired subpages. This buffer
  // must still pass the application snapshot's finite/range validation.
  int readFrame(float *frame);
  int lastError() const { return error_; }

 private:
  bool ready_ = false;
  int error_ = notInitialized;
  // Keep these off the worker stack. Calibration extraction itself uses about
  // 4 KB of nested temporary stack; allocate at least a 12 KB worker stack.
  paramsMLX90640 parameters_ = {};
  uint16_t rawFrame_[834] = {};
};
