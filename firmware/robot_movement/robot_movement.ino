// Adapted from the operator-supplied BIM-Bot.ino, October 27, 2026.
// Uno motor/IR/DHT pins and PWM values are preserved from that source.
// Serial: 9600 baud. No ESP32 camera pins or firmware are changed.
#include <DHT.h>
#include "IR_remote.h"
#include "Keymap.h"
#include "MovementRecorder.h"

// Default: record manual movement only. Enable ONLY for a supervised clear
// bench/test course after Stop/lease/IR obstacle checks. No rear/cliff sensor
// is established; this is timed open-loop playback, not autonomous navigation.
#ifndef BIMBOT_SUPERVISED_RETURN
#define BIMBOT_SUPERVISED_RETURN 0
#endif
// Default 0: the robot never moves by itself. 1 = supervised bench/floor test:
// IR "*" marks the base, waits 5 s, then explores and avoids obstacles.
#ifndef BIMBOT_AUTONOMOUS_EXPLORE
#define BIMBOT_AUTONOMOUS_EXPLORE 0 //change 0 to 1 to turn on exploring omayghad
#endif

DHT dht(9, DHT11);
IRremote ir(3);
const uint8_t RIGHT_IR = A1, LEFT_IR = A2;
void stopMotors() {
  analogWrite(5, 0); analogWrite(6, 0);
  digitalWrite(2, LOW); digitalWrite(4, LOW);
}
void moveForward() { digitalWrite(2,HIGH); digitalWrite(4,LOW); analogWrite(5,50); analogWrite(6,50); }
void moveBackward() { digitalWrite(2,LOW); digitalWrite(4,HIGH); analogWrite(5,50); analogWrite(6,50); }
void turnLeft() { digitalWrite(2,LOW); digitalWrite(4,LOW); analogWrite(5,40); analogWrite(6,40); }
void turnRight() { digitalWrite(2,HIGH); digitalWrite(4,HIGH); analogWrite(5,40); analogWrite(6,40); }
void executeMove(char dir) {
  if(dir=='F')moveForward(); else if(dir=='B')moveBackward();
  else if(dir=='L')turnLeft(); else if(dir=='R')turnRight(); else stopMotors();
}
MovementRecorder recorder(executeMove, BIMBOT_SUPERVISED_RETURN == 1);
char commandId[33] = "-", input[96], ack[64];
uint8_t inputLength = 0;
bool dropping = false, obstacle = false, snapshot = false, fullDump = false;
uint8_t snapshotStage = 0, dumpIndex = 0;
uint32_t snapshotRevision = 0, query = 0;

#if BIMBOT_AUTONOMOUS_EXPLORE
enum ExploreState : uint8_t { EX_OFF, EX_WAIT, EX_FORWARD, EX_BACK, EX_TURN };
ExploreState explore = EX_OFF;
const uint32_t EX_START_DELAY_MS = 5000, EX_BACK_MS = 500;
const uint32_t EX_TURN_MIN_MS = 400, EX_TURN_MAX_MS = 900;
const uint32_t EX_LEG_MAX_MS = 30000;    // trace segments are limited to 60 s
const uint32_t EX_TOTAL_MAX_MS = 540000; // trace total is limited to 10 min
const uint8_t  EX_RESERVE = 4;           // keep room in the 80-segment trace
const uint8_t  EX_STUCK_LIMIT = 6;       // give up after repeated avoidances
uint32_t exploreAt = 0, turnMs = 0;
char turnDir = 'R';
bool turnFlip = false;
uint8_t stuckCount = 0;

bool exploring() { return explore != EX_OFF; }

void endExplore(uint32_t now) {          // clean stop, trace stays valid
  recorder.stop(now);
  recorder.setAutonomous(false);
  explore = EX_OFF;
}
void startExplore(uint32_t now) {        // call right after markBase() succeeds
  explore = EX_WAIT; exploreAt = now; stuckCount = 0;
  recorder.setAutonomous(true);
}
void beginAvoid(uint32_t now, bool leftObs, bool rightObs) {
  if (leftObs && !rightObs) turnDir = 'R';
  else if (rightObs && !leftObs) turnDir = 'L';
  else { turnDir = turnFlip ? 'L' : 'R'; turnFlip = !turnFlip; }
  turnMs = random(EX_TURN_MIN_MS, EX_TURN_MAX_MS);
  explore = EX_BACK; exploreAt = now; stuckCount++;
}
void exploreTick(uint32_t now, bool leftObs, bool rightObs) {
  if (explore == EX_OFF) return;
  MovementRecorder::State s = recorder.state();
  if (s == MovementRecorder::FAULT || s == MovementRecorder::RETURNING) {
    recorder.setAutonomous(false); explore = EX_OFF; return;   // recorder gave up
  }
  if (recorder.count() + EX_RESERVE >= MovementRecorder::CAPACITY ||
      recorder.total() >= EX_TOTAL_MAX_MS || stuckCount >= EX_STUCK_LIMIT) {
    endExplore(now); return;             // trace nearly full or stuck: stop, operator returns
  }
  if (explore == EX_WAIT) {
    if (now - exploreAt < EX_START_DELAY_MS) return;
    explore = EX_FORWARD; exploreAt = now;
  }
  if (explore == EX_FORWARD) {
    if (leftObs || rightObs) { beginAvoid(now, leftObs, rightObs); recorder.autoMove('B', now); return; }
    if (recorder.activeDuration(now) >= EX_LEG_MAX_MS) recorder.stop(now);  // new segment
    recorder.autoMove('F', now);
    if (now - exploreAt >= 1000) stuckCount = 0;                            // real progress
    return;
  }
  if (explore == EX_BACK) {
    recorder.autoMove('B', now);
    if (now - exploreAt >= EX_BACK_MS) { explore = EX_TURN; exploreAt = now; }
    return;
  }
  recorder.autoMove(turnDir, now);       // EX_TURN
  if (now - exploreAt >= turnMs) { explore = EX_FORWARD; exploreAt = now; }
}
#else
bool exploring() { return false; }
void endExplore(uint32_t) {}
void startExplore(uint32_t) {}
void exploreTick(uint32_t, bool, bool) {}
#endif

char stateCode() {
  const char codes[] = "ICSRPXE";
  return codes[recorder.state()];
}
bool hexId(const char *s, uint8_t length) {
  if(strlen(s)!=length)return false;
  for(uint8_t i=0;i<length;i++)if(!isxdigit(s[i]))return false;
  return true;
}
void queueAck(char action, const char *id, const char *nonce, bool accepted) {
  // Stop acknowledgement confirms motor output S even if the retained trace
  // state is cancelled/fault/replay_complete.
  char confirmed=(action=='S' && accepted)?'S':stateCode();
  snprintf(ack,sizeof(ack),"A %c %s %s %c %u %lu\n",action,id,nonce,confirmed,accepted?1:0,(unsigned long)recorder.trace());
}
void command(char *line) {
  char *action=strtok(line," "), *id=strtok(NULL," "), *arg=strtok(NULL," "), *extra=strtok(NULL," ");
  if(!action || !id)return;
  if((!strcmp(action,"Q") || !strcmp(action,"D")) && hexId(id,8) && !arg) {
    query=strtoul(id,NULL,16); fullDump=!strcmp(action,"D");
    snapshot=true; snapshotStage=dumpIndex=0; snapshotRevision=recorder.revision(); return;
  }
  
  if(!hexId(id,32))return;
    if(!strcmp(action,"STOP") && arg && hexId(arg,8) && !extra) {
    if(exploring())endExplore(millis()); else recorder.stop(millis());
    strncpy(commandId,id,sizeof(commandId)); queueAck('S',id,arg,true);
  } else if(!strcmp(action,"KEEP") && arg && hexId(arg,8) && !extra) {
    bool accepted=!strcmp(commandId,id) && recorder.heartbeat(millis()); queueAck('K',id,arg,accepted);
  } else if(!strcmp(action,"RETURN") && arg && extra && hexId(extra,8)) {
    char *end; unsigned long expected=strtoul(arg,&end,10);
    bool accepted=false;
    if(!*end && expected==recorder.trace() && !exploring()) {
      // A retransmitted active command never restarts the path.
      if(!strcmp(commandId,id) && recorder.state()==MovementRecorder::RETURNING) accepted=true;
      else if(strcmp(commandId,id) && recorder.startReturn(millis(),obstacle)) {
        strncpy(commandId,id,sizeof(commandId)); accepted=true;
      }
    }
    queueAck('R',id,extra,accepted);
  }
}
void serviceSerial() {
  // Bounded input work keeps IR Stop and motor deadlines responsive.
  uint8_t budget=32;
  while(Serial.available() && budget--) {
    char c=Serial.read();
    if(c=='\n') {
      if(!dropping) { input[inputLength]='\0'; command(input); }
      inputLength=0; dropping=false;
    } else if(c!='\r' && !dropping) {
      if(inputLength<sizeof(input)-1)input[inputLength++]=c;
      else { dropping=true; inputLength=0; recorder.protocolFault(); }
    }
  }
}
void serviceOutput() {
  if(ack[0]) {
    uint8_t len=strlen(ack);
    if(Serial.availableForWrite()>=len) { Serial.write((const uint8_t*)ack,len); ack[0]='\0'; }
    return;
  }
  if(!snapshot)return;
  char line[64];
  if(recorder.revision()!=snapshotRevision) {
    snprintf(line,sizeof(line),"X %08lx\n",(unsigned long)query);
  } else if(snapshotStage==0) {
    snprintf(line,sizeof(line),"M %08lx %lu %c %c %lu %u %u %u %u %u\n",(unsigned long)query,
      (unsigned long)recorder.trace(),stateCode(),recorder.current(),(unsigned long)recorder.activeDuration(millis()),
      recorder.count(),recorder.returned(),recorder.complete()?1:0,recorder.ready(obstacle)?1:0,recorder.fault());
  } else if(snapshotStage==1) {
    snprintf(line,sizeof(line),"C %08lx %s\n",(unsigned long)query,commandId);
  } else if(fullDump && dumpIndex<recorder.count()) {
    snprintf(line,sizeof(line),"P %08lx %u %c %u\n",(unsigned long)query,dumpIndex,recorder.direction(dumpIndex),recorder.duration(dumpIndex));
  } else snprintf(line,sizeof(line),"E %08lx\n",(unsigned long)query);
  uint8_t len=strlen(line);
  if(Serial.availableForWrite()<len)return;
  Serial.write((const uint8_t*)line,len);
  if(line[0]=='X' || line[0]=='E')snapshot=false;
  else if(snapshotStage<2)snapshotStage++;
  else dumpIndex++;
}
void setup() {
  pinMode(2,OUTPUT);pinMode(5,OUTPUT);pinMode(4,OUTPUT);pinMode(6,OUTPUT);
  stopMotors();
  pinMode(RIGHT_IR,INPUT);pinMode(LEFT_IR,INPUT);
  Serial.begin(9600); dht.begin(); ir.begin();
#if BIMBOT_AUTONOMOUS_EXPLORE
  randomSeed(analogRead(A0));
#endif
  Serial.println(F("BOOT BIMBOT_MOVE_1"));
}

void loop() {
  uint32_t now=millis();
  bool leftObs=digitalRead(LEFT_IR)==LOW, rightObs=digitalRead(RIGHT_IR)==LOW;
  obstacle=digitalRead(RIGHT_IR)==LOW || digitalRead(LEFT_IR)==LOW;
  if(exploring() && obstacle && recorder.current()=='F')recorder.stop(now);
  recorder.tick(now,obstacle);
  serviceSerial();
  uint8_t key=ir.getIrKey(ir.getCode(),IR_TYPE_NORMAL);
  static uint8_t previousKey=0xff;
  static uint32_t keyAt=0;
  if(now-keyAt>=250)previousKey=0xff;
  if(key!=0xff) {
    bool edge=key!=previousKey;
    previousKey=key;keyAt=now;
    if(exploring()) {
      if(key!=IR_KEYCODE_STAR || edge)endExplore(now);
    } else if(key==IR_KEYCODE_OK)recorder.stop(now);
    else if(key==IR_KEYCODE_STAR && edge && !obstacle) {
      if(recorder.markBase(now)) { strcpy(commandId,"-"); startExplore(now); }
    } else if(key==IR_KEYCODE_UP)recorder.manual('F',now,obstacle);
    else if(key==IR_KEYCODE_DOWN)recorder.manual('B',now,obstacle);
    else if(key==IR_KEYCODE_LEFT)recorder.manual('L',now,obstacle);
    else if(key==IR_KEYCODE_RIGHT)recorder.manual('R',now,obstacle);
  }
  exploreTick(now,leftObs,rightObs); 
  recorder.tick(millis(),obstacle);
  serviceOutput();
  // Preserve DHT serial readings. Read only while stopped: DHT timing must not
  // interrupt manual movement/replay deadlines or the query/ack protocol.
  static uint32_t lastDHT=0;
  if(recorder.current()=='S' && recorder.state()!=MovementRecorder::RETURNING && !snapshot && !ack[0] && now-lastDHT>=2000) {
    lastDHT=now;
    float humidity=dht.readHumidity(), temperature=dht.readTemperature();
    if(!isnan(humidity) && !isnan(temperature)) {
      char t[10],h[10],line[32]; dtostrf(temperature,1,2,t);dtostrf(humidity,1,2,h);
      snprintf(line,sizeof(line),"T:%s,H:%s\n",t,h);
      if(Serial.availableForWrite()>=(int)strlen(line))Serial.print(line);
    }
  }
}
