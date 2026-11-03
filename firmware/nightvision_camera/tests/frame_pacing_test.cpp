#include "../frame_pacing.h"
#include <assert.h>
#include <stdint.h>

int main() {
  assert(frameIntervalMs == 125);
  assert(frameDelayMs(1000, 1000) == 125);
  assert(frameDelayMs(1000, 1020) == 105);
  assert(frameDelayMs(1000, 1124) == 1);
  assert(frameDelayMs(1000, 1125) == 1);
  assert(frameDelayMs(1000, 1500) == 1);
  assert(frameDelayMs(UINT32_MAX - 9, 10) == 105);
}
