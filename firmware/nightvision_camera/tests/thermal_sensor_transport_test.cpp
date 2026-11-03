// Native simulated I2C test. No serial, network or physical hardware access.
// Include the implementation so its internal deadline/transport can be tested
// without adding test-only controls to the shipped driver interface.
#include "../thermal_sensor.cpp"
#include <assert.h>
#include <stdio.h>

static void syntheticCalibration() {
  // Synthetic algorithm inputs, not calibration from any physical sensor.
  thermalWire.registers.fill(0);
  for (unsigned i = 0; i < 768; ++i) thermalWire.registers[0x2440 + i] = 2;
  thermalWire.registers[0x2400 + 33] = 10000;
  thermalWire.registers[0x2400 + 48] = 1000;
  thermalWire.registers[0x2400 + 49] = 29127;
  thermalWire.registers[0x2400 + 50] = 8;
  thermalWire.registers[0x2400 + 51] = 0x0100;
  thermalWire.registers[0x2400 + 52] = 0x1111;
  thermalWire.registers[0x2400 + 54] = 0x0101;
  thermalWire.registers[0x2400 + 55] = 0x0101;
  thermalWire.registers[0x2400 + 56] = 0x1000;
  thermalWire.registers[0x0400 + 768] = 1000;
  thermalWire.registers[0x0400 + 778] = 1000;
  thermalWire.registers[0x0400 + 800] = 1000;
  thermalWire.registers[0x0400 + 810] = 0x8000;
}

int main() {
  static ThermalSensor sensor;
  static float frame[768];
  assert(sensor.readFrame(frame) == ThermalSensor::notInitialized);
  assert(!sensor.begin()); // All-zero EEPROM must fail without hanging.
  assert(sensor.lastError() == -MLX90640_EEPROM_DATA_ERROR);
  assert(thermalWire.sda == 14 && thermalWire.scl == 13);
  assert(thermalWire.frequency == 400000 && thermalWire.timeout == 50);
  assert(thermalWire.port == (CONFIG_SCCB_HARDWARE_I2C_PORT1 ? 0 : 1));

  syntheticCalibration();
  thermalWire.failRequest = thermalWire.requestCalls + 2;
  assert(!sensor.begin()); // Failed EEPROM chunk cannot create a ready sensor.
  thermalWire.failRequest = 0;
  assert(sensor.begin());
  assert(thermalWire.registers[0x800D] == expectedControl);
  // Every allowed build must write its selected refresh field without
  // changing the existing chess mode or 18-bit ADC resolution.
  assert((thermalWire.registers[0x800D] & 0x0380) >> 7 == BIMBOT_THERMAL_REFRESH_RATE);
  assert((thermalWire.registers[0x800D] & 0x0C00) >> 10 == 2);
  assert((thermalWire.registers[0x800D] & 0x1000) != 0);

  {
    SensorOperation operation;
    assert(MLX90640_I2CWrite(0x33, 0x2400, 0) == ThermalSensor::unsupportedOperation);
    assert(MLX90640_I2CGeneralReset() == ThermalSensor::unsupportedOperation);
    uint16_t buffer[832]{};
    const size_t before = thermalWire.requestCalls;
    assert(MLX90640_I2CRead(0x33, 0x2400, 832, buffer) == 0);
    assert(thermalWire.requestCalls - before == 26);
    assert(buffer[33] == 10000 && buffer[48] == 1000);
    assert(thermalWire.maximumRead <= 64);
  }

  thermalWire.registers[0x8000] = 0;
  uint32_t started = thermalMockClock;
  assert(sensor.readFrame(frame) == ThermalSensor::timeout);
  assert(uint32_t(thermalMockClock - started) >= 3000);
  assert(uint32_t(thermalMockClock - started) <= 3006);

  thermalMockClock = UINT32_MAX - 30;
  started = thermalMockClock;
  assert(sensor.readFrame(frame) == ThermalSensor::timeout);
  assert(uint32_t(thermalMockClock - started) >= 3000); // millis rollover.

  thermalWire.automaticStatus = 2; // Always repeats subpage 0.
  assert(sensor.readFrame(frame) == ThermalSensor::timeout);
  thermalWire.automaticStatus = 1; // Alternates fresh subpages 0 and 1.
  assert(sensor.readFrame(frame) == 0);
  for (float value : frame) assert(isfinite(value));

  // A captured frame reporting another refresh profile must be rejected,
  // even when its two subpages and temperatures would otherwise be valid.
  const uint16_t configuredControl = thermalWire.registers[0x800D];
  thermalWire.registers[0x800D] ^= 0x0080;
  assert(sensor.readFrame(frame) == ThermalSensor::configurationMismatch);
  thermalWire.registers[0x800D] = configuredControl;
  assert(sensor.readFrame(frame) == 0);

  thermalWire.registers[0x0700] = 0x7FFF; // Invalid auxiliary payload.
  assert(sensor.readFrame(frame) == -MLX90640_FRAME_DATA_ERROR);
  puts("thermal sensor simulated transport tests passed");
}
