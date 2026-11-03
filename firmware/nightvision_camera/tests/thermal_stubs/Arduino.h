#pragma once
#include <stddef.h>
#include <stdint.h>
inline uint32_t thermalMockClock = 0;
inline uint32_t millis() { return thermalMockClock; }
inline void delay(uint32_t duration) { thermalMockClock += duration; }
