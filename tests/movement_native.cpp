#include <assert.h>
#include <iostream>
#include <vector>
#include "../firmware/robot_movement/MovementRecorder.h"
static std::vector<char> outputs;
static void drive(char d) { outputs.push_back(d); }
static void assertStopped(const MovementRecorder &r) { assert(r.current()=='S'); assert(outputs.back()=='S'); }
int main() {
  {
    MovementRecorder r(drive,true);
    assert(!r.ready()); assert(!r.startReturn(0));
    assert(r.markBase(0)); assert(r.manual('F',10));
    assert(r.manual('F',100)); r.tick(200,false);
    assert(r.manual('L',210)); r.manual('L',300); r.stop(410);
    assert(r.count()==2 && r.duration(0)==200 && r.direction(0)=='F');
    assert(r.duration(1)==200 && r.total()==400 && r.complete());
    assert(r.ready()); assert(r.startReturn(500));
    assert(!r.startReturn(510)); assert(!r.markBase(520));
    r.tick(599,false);assertStopped(r);
    r.tick(600,false);assert(r.current()=='R');
    r.tick(800,false);assertStopped(r);assert(r.returned()==1);
    r.tick(900,false);assert(r.current()=='B');
    r.tick(1100,false);assertStopped(r);
    assert(r.state()==MovementRecorder::REPLAY_COMPLETE && r.returned()==2);
    assert(r.count()==2 && r.total()==400 && !r.complete() && !r.ready());
  }
  {
    MovementRecorder r(drive,true);r.markBase(0);r.manual('F',0);r.tick(249,false);
    assert(r.current()=='F');r.tick(250,false);assertStopped(r);
    assert(r.count()==1 && r.duration(0)==250); // Final active segment captured.
    assert(r.startReturn(251));r.tick(351,false);assert(r.current()=='B');
    r.stop(360);assertStopped(r);assert(r.state()==MovementRecorder::CANCELLED);
    assert(!r.complete() && !r.ready() && r.count()==1); // Replay never recorded.
  }
  {
    MovementRecorder r(drive,true);r.markBase(0);r.manual('F',0);r.stop(100);
    r.startReturn(101);r.tick(3101,false);assertStopped(r);
    assert(r.fault()==MovementRecorder::LEASE && !r.complete());
    r.markBase(3200);r.manual('L',3200);r.stop(3300);r.startReturn(3301);
    r.tick(3401,false);r.tick(3402,true);assertStopped(r);
    assert(r.fault()==MovementRecorder::OBSTACLE && !r.complete());
  }
  {
    MovementRecorder r(drive,true);r.markBase(0);
    for(uint32_t i=0;i<80;i++){assert(r.manual(i%2?'L':'F',i*20));r.stop(i*20+10);}
    assert(r.count()==80);assert(!r.manual('F',2000));assertStopped(r);
    assert(r.fault()==MovementRecorder::TRACE_OVERFLOW && !r.complete());
    r.markBase(2100);assert(!r.manual('?',2101));assertStopped(r);
    assert(r.fault()==MovementRecorder::PROTOCOL);
  }
  {
    MovementRecorder r(drive,false);r.markBase(0);r.manual('F',0);r.stop(100);
    assert(!r.ready() && !r.startReturn(100)); // Shipping/default gate.
  }
  {
    MovementRecorder r(drive,true);uint32_t start=0xfffffff0UL;
    r.markBase(start);r.manual('F',start);r.tick(uint32_t(start+249),false);
    assert(r.current()=='F');r.tick(uint32_t(start+250),false);assertStopped(r);
    assert(r.duration(0)==250); // millis() wraparound.
  }
  {
    MovementRecorder r(drive,true);r.markBase(0);r.manual('F',0);
    for(uint32_t t=100;t<=60000;t+=100)r.manual('F',t);
    r.tick(60001,false);assertStopped(r);assert(!r.complete());
    assert(r.fault()==MovementRecorder::DURATION);
  }
  std::cout<<"Movement core: final segment, inverse playback, cancellation, deadman, lease, obstacles, overflow, limits, gating and millis rollover pass.\n";
}
