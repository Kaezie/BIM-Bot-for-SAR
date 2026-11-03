/* HISTORICAL STANDALONE SENSOR TEST. Do not use on either working camera.
 * The complete nightvision_camera sketch now supports thermal alongside video.
 * This replaces video/light/Wi-Fi; use only on an otherwise unused test board.
 * Its older GPIO14/15 wiring differs from the combined sketch's GPIO14/13.
 * GY-MCU90640: VIN->verified 3.3V, GND->GND, PS->GND,
 * SDA->GPIO14, SCL->GPIO15. RX/TX/NC are not connected.
 * Keep the original main-camera firmware and its DHT GPIO13 unchanged.
 * Install Adafruit MLX90640 and its required library dependencies.
 * Reference: Adafruit_MLX90640/examples/MLX90640_simpletest.
 * This file has not been compiled or tested against physical hardware.
 */
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <math.h>

// Uncomment only for an otherwise unused board, never either working camera.
// #define THERMAL_BENCH_TEST_CONFIRMED
#ifndef THERMAL_BENCH_TEST_CONFIRMED
#error "This removes camera/light/Wi-Fi. Use the combined nightvision_camera sketch for the working spare."
#endif

constexpr int THERMAL_SDA = 14;
constexpr int THERMAL_SCL = 15;
Adafruit_MLX90640 mlx;
float thermalFrame[32 * 24];
bool ready = false;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("Standalone thermal test: no camera, DHT, Wi-Fi or motor control.");
  Wire.begin(THERMAL_SDA, THERMAL_SCL);
  Wire.setClock(400000);
  if (!mlx.begin(0x33, &Wire)) {
    Serial.println("MLX90640 not found. Power off and check wiring, PS mode and supply.");
    return;
  }
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_1_HZ);
  ready = true;
  Serial.println("Sensor initialized. Output is 24 rows x 32 Celsius readings.");
}

void loop() {
  if (!ready) { delay(1000); return; }
  if (mlx.getFrame(thermalFrame) != 0) {
    Serial.println("Frame unavailable; no reading published.");
    delay(1000);
    return;
  }
  float minimum = 300, maximum = -40;
  for (int i = 0; i < 768; ++i) {
    float value = thermalFrame[i];
    if (!isfinite(value) || value < -40 || value > 300) {
      Serial.println("Invalid frame; no reading published.");
      delay(1000);
      return;
    }
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
  }
  Serial.print("{\"grid\":[");
  for (int row = 0; row < 24; ++row) {
    if (row) Serial.print(',');
    Serial.print('[');
    for (int col = 0; col < 32; ++col) {
      if (col) Serial.print(',');
      Serial.print(thermalFrame[row * 32 + col], 2);
    }
    Serial.print(']');
  }
  Serial.print("],\"min_temp\":"); Serial.print(minimum, 2);
  Serial.print(",\"max_temp\":"); Serial.print(maximum, 2);
  Serial.println('}');
  delay(1000);
}
