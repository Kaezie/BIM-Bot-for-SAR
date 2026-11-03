#include "thermal_sensor.h"
#include "thermal_config.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>
#include "sdkconfig.h"

extern "C" {
#include "src/mlx90640/MLX90640_I2C_Driver.h"
}

namespace {
#if CONFIG_SCCB_HARDWARE_I2C_PORT1
constexpr uint8_t thermalBusPort = 0;
#elif CONFIG_SCCB_HARDWARE_I2C_PORT0
constexpr uint8_t thermalBusPort = 1;
#else
#error "Identify the camera SCCB controller before allocating the thermal I2C bus."
#endif

constexpr uint8_t sensorAddress = 0x33;
constexpr uint16_t transferTimeoutMs = 50;
constexpr uint16_t wordsPerTransfer = 32; // 64 bytes, below Wire's 128-byte default.
constexpr uint32_t i2cClockHz = 400000;
constexpr uint8_t refreshRate = BIMBOT_THERMAL_REFRESH_RATE;
constexpr uint8_t resolution = 2;  // 18-bit ADC.
constexpr uint16_t expectedControlMask = 0x1F80;
constexpr uint16_t expectedControl = 0x1000 | (resolution << 10) | (refreshRate << 7);

TwoWire thermalWire(thermalBusPort);
bool busStarted = false;
bool operationActive = false;
uint32_t operationStartedAt = 0;

bool operationExpired() {
  return !operationActive || uint32_t(millis() - operationStartedAt) >= ThermalSensor::operationTimeoutMs;
}

struct SensorOperation {
  SensorOperation() {
    operationStartedAt = millis();
    operationActive = true;
  }
  ~SensorOperation() { operationActive = false; }
};

int transferReady(uint8_t address) {
  if (!busStarted || address != sensorAddress) return ThermalSensor::busUnavailable;
  return operationExpired() ? ThermalSensor::timeout : 0;
}
} // namespace

// Transport for the pinned official Melexis calculations. Every transfer is
// bounded, and every callback rechecks the overall operation deadline. Thus the
// upstream data-ready loops also terminate if a sensor ACKs but stops updating.
extern "C" int MLX90640_I2CRead(uint8_t address, uint16_t startAddress,
                               uint16_t words, uint16_t *data) {
  if (!data || words == 0) return -MLX90640_I2C_NACK_ERROR;
  const bool isStatusPoll = startAddress == MLX90640_STATUS_REG && words == 1;
  uint16_t *const first = data;
  while (words) {
    const int ready = transferReady(address);
    if (ready != 0) return ready;
    const uint16_t count = words < wordsPerTransfer ? words : wordsPerTransfer;
    thermalWire.beginTransmission(address);
    if (thermalWire.write(uint8_t(startAddress >> 8)) != 1
        || thermalWire.write(uint8_t(startAddress)) != 1) {
      thermalWire.endTransmission(true);
      return -MLX90640_I2C_NACK_ERROR;
    }
    if (thermalWire.endTransmission(false) != 0)
      return -MLX90640_I2C_NACK_ERROR;
    const size_t bytes = size_t(count) * 2;
    if (thermalWire.requestFrom(address, bytes, true) != bytes)
      return -MLX90640_I2C_NACK_ERROR;
    for (uint16_t i = 0; i < count; ++i) {
      const int high = thermalWire.read();
      const int low = thermalWire.read();
      if (high < 0 || low < 0) return -MLX90640_I2C_NACK_ERROR;
      *data++ = uint16_t((high << 8) | low);
    }
    startAddress += count;
    words -= count;
    if (operationExpired()) return ThermalSensor::timeout;
  }
  if (isStatusPoll && !MLX90640_GET_DATA_READY(*first)) {
    delay(5); // Yield to camera/Wi-Fi/loop and the idle watchdog while waiting.
    if (operationExpired()) return ThermalSensor::timeout;
  }
  return 0;
}

extern "C" int MLX90640_I2CWrite(uint8_t address, uint16_t reg, uint16_t value) {
  const int ready = transferReady(address);
  if (ready != 0) return ready;
  // Only volatile runtime registers are writable. Never change EEPROM or send
  // a general reset to any other device on the board.
  if (reg != MLX90640_STATUS_REG && reg != MLX90640_CTRL_REG)
    return ThermalSensor::unsupportedOperation;
  const uint8_t command[] = {
    uint8_t(reg >> 8), uint8_t(reg), uint8_t(value >> 8), uint8_t(value)
  };
  thermalWire.beginTransmission(address);
  if (thermalWire.write(command, sizeof(command)) != sizeof(command)) {
    thermalWire.endTransmission(true);
    return -MLX90640_I2C_NACK_ERROR;
  }
  if (thermalWire.endTransmission(true) != 0)
    return -MLX90640_I2C_NACK_ERROR;
  return operationExpired() ? ThermalSensor::timeout : 0;
}

extern "C" void MLX90640_I2CInit(void) {}
extern "C" void MLX90640_I2CFreqSet(int) {}
extern "C" int MLX90640_I2CGeneralReset(void) {
  return ThermalSensor::unsupportedOperation;
}

bool ThermalSensor::begin() {
  ready_ = false;
  error_ = busUnavailable;
  if (!busStarted) {
    if (!thermalWire.begin(sdaPin, sclPin, i2cClockHz)) return false;
    thermalWire.setTimeOut(transferTimeoutMs);
    busStarted = true;
  }
  SensorOperation operation;
  // EEPROM fits the raw-frame member and is no longer needed after extraction.
  memset(rawFrame_, 0, sizeof(rawFrame_));
  error_ = MLX90640_DumpEE(sensorAddress, rawFrame_);
  if (error_ != 0) return false;
  error_ = MLX90640_ExtractParameters(rawFrame_, &parameters_);
  if (error_ != 0) return false;
  if (operationExpired()) { error_ = timeout; return false; }
  if ((error_ = MLX90640_SetChessMode(sensorAddress)) != 0
      || (error_ = MLX90640_SetResolution(sensorAddress, resolution)) != 0
      || (error_ = MLX90640_SetRefreshRate(sensorAddress, refreshRate)) != 0) return false;
  uint16_t control = 0;
  error_ = MLX90640_I2CRead(sensorAddress, MLX90640_CTRL_REG, 1, &control);
  if (error_ != 0) return false;
  if ((control & expectedControlMask) != expectedControl) {
    error_ = configurationMismatch;
    return false;
  }
  ready_ = true;
  error_ = 0;
  return true;
}

int ThermalSensor::readFrame(float *frame) {
  if (!ready_) return error_ = notInitialized;
  if (!frame) return error_ = invalidFrame;
  SensorOperation operation;
  for (size_t i = 0; i < MLX90640_PIXEL_NUM; ++i) frame[i] = NAN;
  unsigned seenPages = 0;
  while (seenPages != 3) {
    if (operationExpired()) return error_ = timeout;
    memset(rawFrame_, 0, sizeof(rawFrame_));
    const int page = MLX90640_GetFrameData(sensorAddress, rawFrame_);
    if (page < 0) return error_ = page;
    if (page > 1) return error_ = invalidFrame;
    if ((rawFrame_[832] & expectedControlMask) != expectedControl)
      return error_ = configurationMismatch;
    const float ambient = MLX90640_GetTa(rawFrame_, &parameters_);
    if (!isfinite(ambient)) return error_ = invalidFrame;
    MLX90640_CalculateTo(rawFrame_, &parameters_, 0.95f, ambient - 8.0f, frame);
    seenPages |= 1U << page;
    delay(1);
  }
  MLX90640_BadPixelsCorrection(parameters_.brokenPixels, frame, 1, &parameters_);
  MLX90640_BadPixelsCorrection(parameters_.outlierPixels, frame, 1, &parameters_);
  if (operationExpired()) return error_ = timeout;
  return error_ = 0;
}
