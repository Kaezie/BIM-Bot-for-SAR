#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// A single reusable multipart packet, never a queue. Staging lets the caller
// return the camera's DMA buffer before a potentially slow network write.
class StreamPacket {
 public:
  using Resize = void *(*)(void *, size_t);
  using Release = void (*)(void *);
  static constexpr size_t maxCapacity = 160 * 1024; // Bounded QVGA staging RAM.

  explicit StreamPacket(Resize resize = realloc, Release release = free)
      : resize_(resize), release_(release) {}
  ~StreamPacket() { release_(data_); }
  StreamPacket(const StreamPacket &) = delete;
  StreamPacket &operator=(const StreamPacket &) = delete;

  bool stage(const uint8_t *jpeg, size_t size) {
    length_ = 0;
    if (!jpeg || size == 0 || size > maxCapacity - 128) return false;
    char header[128];
    const int headerLength = snprintf(header, sizeof(header),
        "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
        (unsigned)size);
    if (headerLength <= 0 || size_t(headerLength) >= sizeof(header)) return false;
    const size_t needed = size_t(headerLength) + size + 2;
    if (needed > capacity_) {
      // Round growth to avoid reallocating for every small JPEG-size variation.
      const size_t capacity = (needed + 4095) & ~size_t(4095);
      void *next = resize_(data_, capacity);
      if (!next) return false;
      data_ = static_cast<uint8_t *>(next);
      capacity_ = capacity;
    }
    memcpy(data_, header, size_t(headerLength));
    memcpy(data_ + headerLength, jpeg, size);
    memcpy(data_ + headerLength + size, "\r\n", 2);
    length_ = needed;
    return true;
  }

  const char *data() const { return reinterpret_cast<const char *>(data_); }
  size_t size() const { return length_; }

 private:
  Resize resize_;
  Release release_;
  uint8_t *data_ = nullptr;
  size_t capacity_ = 0;
  size_t length_ = 0;
};
