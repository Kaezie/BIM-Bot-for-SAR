#pragma once
#include <stdint.h>

// Portable state machine: no Arduino calls, heap allocation, network or delay.
// Motor pins and speeds remain in the supplied-sketch adapter.
class MovementRecorder {
 public:
  static const uint8_t CAPACITY = 80;
  enum State : uint8_t { IDLE, RECORDING, STOPPED, RETURNING, REPLAY_COMPLETE, CANCELLED, FAULT };
  enum Fault : uint8_t { NONE, TRACE_OVERFLOW, DURATION, LEASE, OBSTACLE, PROTOCOL };
  typedef void (*Drive)(char);
  explicit MovementRecorder(Drive drive, bool supervisedReturn = false)
      : drive_(drive), enabled_(supervisedReturn) {}

  bool markBase(uint32_t now) {
    if (current_ != 'S' || state_ == RETURNING) return false;
    drive_('S'); count_ = returned_ = 0; total_ = 0;
    trace_++; complete_ = true; fault_ = NONE; state_ = STOPPED;
    changed_++; since_ = lastManual_ = phase_ = now;
    return true; // Operator-declared starting point, never a measured GPS fix.
  }

  bool manual(char dir, uint32_t now, bool obstacle = false) {
    if (!validDirection(dir)) { fail(PROTOCOL); return false; }
    if (dir == 'S') { stop(now); return true; }
    if (state_ == RETURNING) { stop(now); return false; }
    if (fault_ != NONE || obstacle) { if (obstacle) fail(OBSTACLE); return false; }
    lastManual_ = now;
    if (dir == current_) return true;
    if (!flush(now)) return false;
    if (count_ >= CAPACITY) { fail(TRACE_OVERFLOW); return false; }
    drive_('S'); drive_(dir); current_ = dir; since_ = now;
    state_ = RECORDING; changed_++;
    return true;
  }

  void stop(uint32_t now) {
    if (state_ == RETURNING) {
      drive_('S'); current_ = 'S'; state_ = CANCELLED;
      complete_ = false; changed_++; return;
    }
    if (!flush(now)) return;
    drive_('S'); current_ = 'S';
    if (state_ != FAULT && state_ != REPLAY_COMPLETE && state_ != CANCELLED) state_ = STOPPED;
    changed_++;
  }

  bool startReturn(uint32_t now, bool obstacle = false) {
    if (!ready(obstacle)) return false;
    drive_('S'); state_ = RETURNING; current_ = 'S';
    cursor_ = count_ - 1; returned_ = 0; running_ = false;
    phase_ = lease_ = now; changed_++; return true;
  }

  bool heartbeat(uint32_t now) {
    if (state_ != RETURNING) return false;
    lease_ = now; return true;
  }

  void tick(uint32_t now, bool obstacle) {
    if (current_ != 'S' && obstacle) { fail(OBSTACLE); return; }
    if (state_ == RECORDING) {
      if (uint32_t(now - since_) > 60000UL || total_ + uint32_t(now - since_) > 600000UL) { fail(DURATION); return; }
      if (uint32_t(now - lastManual_) >= 250UL) stop(now);
      return;
    }
    if (state_ != RETURNING) return;
    if (obstacle) { fail(OBSTACLE); return; }
    if (uint32_t(now - lease_) >= 3000UL) { fail(LEASE); return; }
    if (!running_) {
      if (uint32_t(now - phase_) < 100UL) return; // Motors off between segments.
      current_ = inverse(directions_[cursor_]);
      drive_(current_); since_ = now; running_ = true; changed_++;
    } else if (uint32_t(now - since_) >= durations_[cursor_]) {
      drive_('S'); current_ = 'S'; running_ = false;
      returned_++; cursor_--; phase_ = now; changed_++;
      if (cursor_ < 0) { state_ = REPLAY_COMPLETE; complete_ = false; }
    }
  }

  void protocolFault() { fail(PROTOCOL); }
  bool ready(bool obstacle = false) const {
    return enabled_ && complete_ && count_ && state_ == STOPPED && current_ == 'S' && !obstacle && fault_ == NONE;
  }
  static bool validDirection(char d) { return d == 'F' || d == 'B' || d == 'L' || d == 'R' || d == 'S'; }
  static char inverse(char d) { return d == 'F' ? 'B' : d == 'B' ? 'F' : d == 'L' ? 'R' : d == 'R' ? 'L' : 'S'; }
  State state() const { return state_; }
  Fault fault() const { return fault_; }
  char current() const { return current_; }
  uint8_t count() const { return count_; }
  uint8_t returned() const { return returned_; }
  bool complete() const { return complete_; }
  uint32_t trace() const { return trace_; }
  uint32_t revision() const { return changed_; }
  uint32_t total() const { return total_; }
  char direction(uint8_t i) const { return i < count_ ? directions_[i] : 'S'; }
  uint16_t duration(uint8_t i) const { return i < count_ ? durations_[i] : 0; }
  uint32_t activeDuration(uint32_t now) const { return current_ == 'S' ? 0 : uint32_t(now - since_); }

 private:
  bool flush(uint32_t now) {
    if (current_ == 'S') return true;
    uint32_t elapsed = uint32_t(now - since_);
    if (elapsed && (count_ >= CAPACITY || elapsed > 60000UL || total_ + elapsed > 600000UL)) {
      fail(count_ >= CAPACITY ? TRACE_OVERFLOW : DURATION); return false;
    }
    if (elapsed) {
      directions_[count_] = current_; durations_[count_] = uint16_t(elapsed);
      count_++; total_ += elapsed;
    }
    drive_('S'); current_ = 'S'; changed_++; return true;
  }
  void fail(Fault reason) {
    drive_('S'); current_ = 'S'; state_ = FAULT; fault_ = reason;
    complete_ = false; running_ = false; changed_++;
  }
  Drive drive_;
  bool enabled_, complete_ = false, running_ = false;
  State state_ = IDLE;
  Fault fault_ = NONE;
  uint8_t count_ = 0, returned_ = 0;
  int8_t cursor_ = -1;
  char current_ = 'S', directions_[CAPACITY] = {};
  uint16_t durations_[CAPACITY] = {};
  uint32_t trace_ = 0, changed_ = 0, total_ = 0, since_ = 0, phase_ = 0, lease_ = 0, lastManual_ = 0;
};
