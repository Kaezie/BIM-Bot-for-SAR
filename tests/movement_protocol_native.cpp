#include "firmware_fakes/Arduino.h"
#include <assert.h>
#include <iostream>
uint32_t fakeMillis=0;
int fakePins[24]={};
FakeSerial Serial;
// Substitute only the IR hardware decoder; execute the actual .ino loop,
// serial parser, output scheduler, pin adapter and recorder state machine.
#define IRremote_h
struct IRremote {
  uint8_t next=0xff;
  explicit IRremote(int){} void begin(){}
  uint8_t getCode(){uint8_t value=next;next=0xff;return value;}
  uint8_t getIrKey(uint8_t value,uint8_t){return value;}
};
#define BIMBOT_SUPERVISED_RETURN 1
#include "../firmware/robot_movement/robot_movement.ino"
static void pump(int n=25){for(int i=0;i<n;i++)loop();}
static void inputLine(const std::string &s){Serial.receive(s+"\n");pump();}
int main(){
  fakePins[A1]=fakePins[A2]=HIGH;setup();
  assert(Serial.output.find("BOOT BIMBOT_MOVE_1")!=std::string::npos);
  assert(fakePins[5]==0 && fakePins[6]==0);
  ir.next=IR_KEYCODE_STAR;pump();assert(recorder.complete() && recorder.trace()==1);
  fakeMillis=10;ir.next=IR_KEYCODE_UP;pump();
  assert(fakePins[2]==HIGH && fakePins[4]==LOW && fakePins[5]==50 && fakePins[6]==50);
  fakeMillis=260;pump();assert(recorder.current()=='S' && recorder.count()==1);
  assert(recorder.duration(0)==250);
  Serial.output.clear();inputLine("D 0123abcd");
  assert(Serial.output.find("M 0123abcd 1 S S 0 1 0 1 1 0\n")!=std::string::npos);
  assert(Serial.output.find("C 0123abcd -\n")!=std::string::npos);
  assert(Serial.output.find("P 0123abcd 0 F 250\n")!=std::string::npos);
  assert(Serial.output.find("E 0123abcd\n")!=std::string::npos);
  for(size_t start=0;start<Serial.output.size();){
    size_t end=Serial.output.find('\n',start);assert(end!=std::string::npos);assert(end-start+1<=63);start=end+1;
  }
  const std::string id(32,'a');Serial.output.clear();
  inputLine("RETURN "+id+" 1 1234abcd");assert(recorder.state()==MovementRecorder::RETURNING);
  assert(Serial.output.find("A R "+id+" 1234abcd R 1 1\n")!=std::string::npos);
  fakeMillis=360;pump();assert(recorder.current()=='B');
  inputLine("RETURN "+id+" 1 2345abcd");assert(recorder.current()=='B'); // No restart.
  Serial.output.clear();inputLine("STOP "+id+" 3456abcd");
  assert(recorder.state()==MovementRecorder::CANCELLED && fakePins[5]==0 && fakePins[6]==0);
  assert(Serial.output.find("A S "+id+" 3456abcd S 1 1\n")!=std::string::npos);
  fakeMillis=700;ir.next=IR_KEYCODE_STAR;pump();
  fakeMillis=710;ir.next=IR_KEYCODE_UP;pump();fakePins[A1]=LOW;pump();
  assert(recorder.state()==MovementRecorder::FAULT && fakePins[5]==0 && fakePins[6]==0);
  fakePins[A1]=HIGH;Serial.receive(std::string(110,'z')+"\n");pump();
  assert(recorder.fault()==MovementRecorder::PROTOCOL);
  Serial.capacity=0;inputLine("Q abcdef01");assert(snapshot);
  Serial.capacity=64;pump();assert(!snapshot);
  std::cout<<"Actual Uno sketch protocol: motor mapping, IR start/deadman, complete dump, bounded serial lines, return idempotency, Stop acknowledgement, obstacle/protocol faults and output backpressure pass.\n";
}
