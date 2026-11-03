#pragma once

// Enable only after confirming the spare board, empty/unused microSD slot,
// SDA14/SCL13 wiring, GY carrier I2C mode and suitable 3.3 V power/signals.
// Kept OFF until those physical checks are confirmed. Camera/light still work.
// A compile-time override is used for hardware-free enabled-build verification.
#ifndef BIMBOT_THERMAL_ENABLED
#define BIMBOT_THERMAL_ENABLED 0
#endif

// Melexis refresh encoding. Keep the verified code 2 default (2 subpages/s,
// about 1 complete image/s). Code 3 gives 4 subpages/s, about 2 complete
// images/s; code 4 is a bounded test profile for 8 subpages/s, about 4 complete
// images/s. Actual speed/noise/load must be checked on the identified spare.
#ifndef BIMBOT_THERMAL_REFRESH_RATE
#define BIMBOT_THERMAL_REFRESH_RATE 2
#endif
#if BIMBOT_THERMAL_REFRESH_RATE != 2 && BIMBOT_THERMAL_REFRESH_RATE != 3 && BIMBOT_THERMAL_REFRESH_RATE != 4
#error "Use thermal refresh code 2, 3 or the bounded test profile 4."
#endif
