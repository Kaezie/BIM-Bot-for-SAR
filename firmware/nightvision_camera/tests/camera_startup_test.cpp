#include "../camera_startup.h"
#include <assert.h>
#include <stdint.h>

int main() {
  CameraStartup startup;
  uint32_t now = 150;
  startup.begin(now);
  assert(!startup.due(649));
  assert(startup.due(650));
  unsigned attempts = 0;
  unsigned services = 0;
  bool initialized = false;
  // Fault injection: two slow failed probes, then a successful third probe.
  // Model a loop that keeps serving Wi-Fi/control work between camera retries.
  while (now < 15000) {
    ++services;
    if (startup.due(now)) {
      ++attempts;
      now += 750; // Time spent in the real sensor probe.
      initialized = attempts == 3;
      startup.complete(now, initialized);
      assert(!startup.due(now));
      if (!initialized) {
        assert(!startup.due(now + CameraStartup::retryMs - 1));
        assert(startup.due(now + CameraStartup::retryMs));
      }
    }
    now += 50;
  }
  assert(initialized && attempts == 3 && services > 100);
  assert(!startup.due(UINT32_MAX)); // Never reinitialize a running camera.

  startup.begin(UINT32_MAX - 200);
  assert(!startup.due(298)); // 499 ms across millis() rollover.
  assert(startup.due(299));
  startup.complete(UINT32_MAX - 100, false);
  assert(!startup.due(2898));
  assert(startup.due(2899));
}
