#pragma once
#include "Arduino.h"
#include <algorithm>
#include <array>
#include <vector>

class TwoWire {
 public:
  explicit TwoWire(uint8_t number) : port(number) {}
  uint8_t port;
  int sda = -1, scl = -1;
  uint32_t frequency = 0;
  uint16_t timeout = 0;
  size_t requestCalls = 0, failRequest = 0, maximumRead = 0;
  uint32_t transferDuration = 1;
  unsigned automaticStatus = 0, nextPage = 0;
  std::array<uint16_t, 65536> registers{};
  bool begin(int dataPin, int clockPin, uint32_t speed) {
    sda = dataPin; scl = clockPin; frequency = speed; return true;
  }
  void setTimeOut(uint16_t value) { timeout = value; }
  void beginTransmission(uint8_t) { outgoing.clear(); }
  size_t write(uint8_t value) { outgoing.push_back(value); return 1; }
  size_t write(const uint8_t *values, size_t count) {
    outgoing.insert(outgoing.end(), values, values + count); return count;
  }
  uint8_t endTransmission(bool) {
    if (outgoing.size() < 2) return 1;
    selected = uint16_t((outgoing[0] << 8) | outgoing[1]);
    if (outgoing.size() == 4)
      registers[selected] = uint16_t((outgoing[2] << 8) | outgoing[3]);
    return 0;
  }
  size_t requestFrom(uint8_t, size_t count, bool) {
    ++requestCalls;
    thermalMockClock += transferDuration;
    maximumRead = std::max(maximumRead, count);
    if (requestCalls == failRequest) return 0;
    incoming.clear(); incomingIndex = 0;
    for (size_t i = 0; i < count / 2; ++i) {
      uint16_t value = registers[uint16_t(selected + i)];
      if (selected == 0x8000 && automaticStatus) {
        value = 0x0008 | nextPage;
        if (automaticStatus == 1) nextPage ^= 1;
      }
      incoming.push_back(uint8_t(value >> 8));
      incoming.push_back(uint8_t(value));
    }
    return count;
  }
  int read() { return incomingIndex < incoming.size() ? incoming[incomingIndex++] : -1; }
 private:
  uint16_t selected = 0;
  size_t incomingIndex = 0;
  std::vector<uint8_t> outgoing, incoming;
};
