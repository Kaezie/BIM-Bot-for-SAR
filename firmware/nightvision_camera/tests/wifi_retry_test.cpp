#include "../wifi_retry.h"
#include <assert.h>
#include <stdint.h>

int main() {
  WifiRetry retry;
  retry.attempted(1000);
  // An attempt without a reported result is left alone until the stall limit.
  assert(!retry.due(1000 + WifiRetry::failedRetryMs));
  assert(!retry.due(1000 + WifiRetry::stalledRetryMs - 1));
  assert(retry.due(1000 + WifiRetry::stalledRetryMs));

  // A reported failure (hotspot not started yet) retries after 3 s, not 30 s.
  retry.attempted(5000);
  retry.failed();
  assert(!retry.due(5000 + WifiRetry::failedRetryMs - 1));
  assert(retry.due(5000 + WifiRetry::failedRetryMs));

  // A new attempt clears the previous failure.
  retry.attempted(9000);
  assert(!retry.due(9000 + WifiRetry::failedRetryMs));

  // Losing a long-lived connection retries at once.
  retry.attempted(10000);
  retry.failed();
  assert(retry.due(10000 + 600000));

  // millis() rollover.
  retry.attempted(UINT32_MAX - 999);
  retry.failed();
  assert(!retry.due(1999));
  assert(retry.due(2000));
}
