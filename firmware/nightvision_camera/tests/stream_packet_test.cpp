#include "../stream_packet.h"
#include <algorithm>
#include <assert.h>
#include <string>
#include <vector>

static size_t allocations = 0, frees = 0;
static bool failAllocation = false;
static void *resize(void *buffer, size_t size) {
  ++allocations;
  assert(size <= StreamPacket::maxCapacity);
  return failAllocation ? nullptr : realloc(buffer, size);
}
static void release(void *buffer) { ++frees; free(buffer); }

int main() {
  {
    StreamPacket packet(resize, release);
    std::vector<uint8_t> cameraBuffer = {0xff, 0xd8, 1, 2, 3, 0xff, 0xd9};
    assert(packet.stage(cameraBuffer.data(), cameraBuffer.size()));
    const std::string expected = std::string(
        "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 7\r\n\r\n")
        + std::string(reinterpret_cast<char *>(cameraBuffer.data()), cameraBuffer.size()) + "\r\n";
    assert(std::string(packet.data(), packet.size()) == expected);
    // Camera capture may immediately reuse/overwrite its returned DMA buffer
    // while a slow sender still owns this immutable packet.
    std::fill(cameraBuffer.begin(), cameraBuffer.end(), 42);
    assert(std::string(packet.data(), packet.size()) == expected);
    assert(allocations == 1);

    // Replacing the packet reuses storage; it cannot queue earlier images.
    cameraBuffer.assign({0xff, 0xd8, 99, 0xff, 0xd9});
    assert(packet.stage(cameraBuffer.data(), cameraBuffer.size()));
    assert(allocations == 1);
    assert(std::string(packet.data(), packet.size()).find("Content-Length: 5\r\n") != std::string::npos);
    assert(packet.data()[packet.size() - 5] == 99);

    assert(!packet.stage(nullptr, 5));
    assert(packet.size() == 0);
    assert(!packet.stage(cameraBuffer.data(), 0));
    assert(!packet.stage(cameraBuffer.data(), StreamPacket::maxCapacity));
    assert(allocations == 1);

    // Failed growth must not expose a previous image as a new packet; the old
    // allocation is retained for safe cleanup/reuse.
    failAllocation = true;
    std::vector<uint8_t> larger(8192, 1);
    assert(!packet.stage(larger.data(), larger.size()));
    assert(packet.size() == 0);
    failAllocation = false;
    assert(packet.stage(larger.data(), larger.size()));
    assert(packet.size() > larger.size());
  }
  assert(frees == 1);
}
