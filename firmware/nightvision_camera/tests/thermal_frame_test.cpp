#include "../thermal_frame.h"
#include <cassert>
#include <iostream>
#include <limits>

int main(int argc, char **argv) {
  ThermalFrame frame;
  float samples[ThermalFrame::pixels];
  for (size_t i = 0; i < ThermalFrame::pixels; ++i) samples[i] = 20 + float(i % 17);
  samples[0] = -40;
  samples[ThermalFrame::pixels - 1] = 300;
  char json[ThermalFrame::jsonCapacity];
  assert(!frame.fresh(100));
  assert(!encodeThermalFrame(frame, 100, json, sizeof(json)));
  assert(frame.publish(samples, 100));
  assert(frame.minimum == -40 && frame.maximum == 300 && frame.sequence == 1);
  assert(frame.fresh(5099) && !frame.fresh(5100));
  assert(encodeThermalFrame(frame, 350, json, sizeof(json)));
  if (argc > 1 && std::strcmp(argv[1], "--json") == 0) {
    std::cout << json << '\n';
    return 0;
  }

  // The buffer guarantee covers an image containing the longest formatted value.
  for (float &value : samples) value = -40;
  assert(frame.publish(samples, 200));
  assert(encodeThermalFrame(frame, 201, json, sizeof(json)));
  const size_t required = std::strlen(json) + 1;
  assert(!encodeThermalFrame(frame, 201, json, required - 1));
  assert(encodeThermalFrame(frame, 201, json, required));
  assert(!encodeThermalFrame(frame, 201, nullptr, 20));
  assert(!encodeThermalFrame(frame, 201, json, 0));

  // A partial subpage or any invalid edge pixel invalidates the previous frame.
  const float invalid[] = {std::numeric_limits<float>::quiet_NaN(),
    std::numeric_limits<float>::infinity(), -40.01f, 300.01f};
  for (float value : invalid) {
    assert(frame.publish(samples, 300));
    const auto sequence = frame.sequence;
    samples[ThermalFrame::pixels - 1] = value;
    assert(!frame.publish(samples, 301));
    assert(!frame.fresh(301) && frame.sequence == sequence);
    assert(!encodeThermalFrame(frame, 301, json, sizeof(json)));
    samples[ThermalFrame::pixels - 1] = 25;
  }
  assert(!frame.publish(nullptr, 301));
  assert(frame.publish(samples, UINT32_MAX - 100));
  assert(frame.fresh(150)); // millis() rollover: age 251ms.
  assert(!frame.fresh(4899)); // exactly 5000ms old across rollover.
  assert(encodeThermalFrame(frame, 150, json, sizeof(json)));
  assert(std::strstr(json, "\"frame_age_ms\":251"));
  frame.invalidate();
  assert(!encodeThermalFrame(frame, 150, json, sizeof(json)));
  assert(frame.publish(samples, 160)); // recovery after failure.
  assert(encodeThermalFrame(frame, 160, json, sizeof(json)));
  std::cout << "Thermal validation, expiry, rollover, recovery and JSON bounds passed.\n";
}
