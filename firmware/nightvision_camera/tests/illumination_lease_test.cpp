#include "../illumination_lease.h"
#include <assert.h>
#include <stdint.h>

int main() {
  IlluminationLease lease;
  assert(!lease.enabled);
  lease.set(true, 100);
  assert(!lease.expire(15099, true) && lease.enabled);
  assert(lease.expire(15100, true) && !lease.enabled);
  lease.set(true, 20000);
  lease.set(true, 30000); // A heartbeat renews the lease.
  assert(!lease.expire(40000, true) && lease.enabled);
  assert(lease.expire(40001, false) && !lease.enabled);
  lease.set(true, UINT32_MAX - 9999);
  assert(!lease.expire(4999, true) && lease.enabled);
  assert(lease.expire(5000, true) && !lease.enabled);
  lease.set(false, 6000);
  assert(!lease.enabled && !lease.expire(22000, true));

  bool value = false;
  assert(parseLightQuery("enabled=1", value) && value);
  assert(parseLightQuery("enabled=0", value) && !value);
  const char *invalid[] = {"", "enabled=", "enabled=true", "enabled=2",
      "enabled=01", "enabled=%31", "enabled=1&enabled=0", "enabled=1&x=1",
      "x=1", "Enabled=1", "enabled=1 ", "enabled=1#"};
  for (const char *query : invalid) assert(!parseLightQuery(query, value));
}
