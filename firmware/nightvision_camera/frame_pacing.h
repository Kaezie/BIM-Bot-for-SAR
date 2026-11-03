#pragma once
#include <stdint.h>

// Conservative target while sharing the original camera's hotspot, which
// relays every Night frame. The dashboard shows about 6 fps and analyses 2 fps,
// so faster sending only adds hotspot load and supply current.
// This is an upper pacing target, not measured camera performance.
static constexpr uint32_t streamTargetFPS = 8;
static constexpr uint32_t frameIntervalMs = (1000 + streamTargetFPS - 1) / streamTargetFPS;

inline uint32_t frameDelayMs(uint32_t startedAt, uint32_t now) {
  const uint32_t elapsed = now - startedAt;
  return elapsed < frameIntervalMs ? frameIntervalMs - elapsed : 1;
}
