# Pinned MLX90640 calculation source

Upstream: <https://github.com/melexis/mlx90640-library>

Commit: `f6be7ca1d4a55146b705f3d347f84b773b29cc86`

Copied `functions/MLX90640_API.c`, `headers/MLX90640_API.h`,
`headers/MLX90640_I2C_Driver.h`, and `LICENSE`. Melexis copyrights and the
Apache 2.0 license are retained. This is sensor calibration/calculation code,
not an Adafruit Arduino library dependency.

Local changes:

- Relative includes and a self-contained `<stdint.h>` include.
- Propagate every failed runtime-register write and invalid auxiliary frame
  instead of continuing with stale/uninitialized auxiliary values.
- Calibration scale extraction rejects nonfinite/nonpositive values and has a
  finite iteration bound; failures propagate as `-MLX90640_EEPROM_DATA_ERROR`.
  Alpha conversion also rejects out-of-range values before integer conversion.
- Normalize line endings to LF.

The adjacent `thermal_sensor.cpp` implements the transport. Its independent
ESP32 I2C controller is the opposite of the configured camera SCCB controller.
All reads are chunked to 64 bytes and have a 50 ms transfer timeout. A complete
begin/read operation has a 3000 ms deadline, checked at every callback/chunk;
the upstream data-ready loop exits through the callback error when it expires.
A not-ready status poll yields 5 ms, so it cannot busy-spin while waiting.
Physical timeout completion can exceed the deadline by one bounded transfer
and scheduler latency; the timeout is not a hard real-time guarantee.

No general-call resets or EEPROM writes are supported. Only status `0x8000`
and volatile configuration `0x800D` writes are allowed. A full image requires
both distinct subpages. The driver uses chess, 18-bit, two subpages per second,
emissivity 0.95 and a reflected-temperature assumption of package temperature
minus 8 °C, matching the Adafruit open-air example assumptions. These values
are not a body-temperature calibration or fever measurement.

`BIMBOT_THERMAL_REFRESH_RATE` in `thermal_config.h` preserves refresh code 2
by default. A compile-time override of 3 is a bounded candidate for four
subpages per second (nominally two complete images per second). Other values
are rejected at compile time; pins, ADC resolution, deadlines, video pacing
and light behavior stay unchanged. Build and simulated-transport checks do not
verify the faster profile's physical speed, noise, power or combined load.

Call `begin()` and `readFrame()` from exactly one worker. The instance contains
about 8 KB of buffers/calibration and should be static, with at least 12 KB of
worker stack for the upstream extraction scratch arrays. Keep driver calls out
of the camera/HTTP/light-lease tasks. Publish only after separate complete-frame
finite/range/freshness validation. Software compilation and simulated transport
tests do not establish sensor wiring, temperatures, power capacity or video FPS.
