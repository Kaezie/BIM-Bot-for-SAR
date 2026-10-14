/* Reference Uno obstacle-avoidance controller, NOT area-coverage navigation.
 * Configure the nine pins below after checking your shield wiring.
 * ESP32 bridge -> Uno hardware Serial at 115200: START <id>, KEEP <id>, STOP <id>
 * Uno -> bridge: ACK <id> searching|stopped, RANGE <cm>, FAULT <id> sensor|lease
 * Bridge must translate these to the HTTP contracts in docs/FEATURE_INTEGRATION.md.
 * Remove motors / raise wheels for the first test. No reverse movement is used:
 * a single front ultrasonic sensor cannot check obstacles behind the robot.
 */
#ifndef BIMBOT_WIRING_VERIFIED
#error "Define BIMBOT_WIRING_VERIFIED and all pin macros after verifying actual wiring."
#endif
#ifndef MOTOR_EN_A
#error "Define MOTOR_EN_A, MOTOR_EN_B, MOTOR_IN_1..4, US_TRIG, US_ECHO, and STOP_PIN."
#endif

const unsigned long LEASE_MS = 8000;
const unsigned long RANGE_PERIOD_MS = 100;
const float STOP_DISTANCE_CM = 30.0; // Calibrate to measured stopping distance.
const byte MOTOR_SPEED = 110;
String missionId = "";
String line = "";
bool searching = false;
unsigned long leaseAt = 0, rangeAt = 0, phaseAt = 0;
float distanceCm = -1;
enum Phase { FORWARD, BRAKE, TURN };
Phase phase = BRAKE;

void halt() {
  analogWrite(MOTOR_EN_A, 0); analogWrite(MOTOR_EN_B, 0);
  digitalWrite(MOTOR_IN_1, LOW); digitalWrite(MOTOR_IN_2, LOW);
  digitalWrite(MOTOR_IN_3, LOW); digitalWrite(MOTOR_IN_4, LOW);
}
void drive(bool turning) {
  digitalWrite(MOTOR_IN_1, HIGH); digitalWrite(MOTOR_IN_2, LOW);
  // A forward arc with one stationary wheel, rather than reversing unseen.
  digitalWrite(MOTOR_IN_3, turning ? LOW : HIGH); digitalWrite(MOTOR_IN_4, LOW);
  analogWrite(MOTOR_EN_A, MOTOR_SPEED); analogWrite(MOTOR_EN_B, turning ? 0 : MOTOR_SPEED);
}
void acknowledge(const String &id, const char *state) {
  Serial.print("ACK "); Serial.print(id); Serial.print(' '); Serial.println(state);
}
void fault(const char *reason) {
  halt(); searching = false;
  Serial.print("FAULT "); Serial.print(missionId); Serial.print(' '); Serial.println(reason);
}
float measure() {
  digitalWrite(US_TRIG, LOW); delayMicroseconds(2);
  digitalWrite(US_TRIG, HIGH); delayMicroseconds(10); digitalWrite(US_TRIG, LOW);
  unsigned long duration = pulseIn(US_ECHO, HIGH, 25000UL); // Bounded echo wait.
  return duration ? duration * 0.0343 / 2 : -1;
}
void command(const String &input) {
  int split = input.indexOf(' ');
  if (split < 1) return;
  String action = input.substring(0, split), id = input.substring(split + 1);
  if (id.length() != 32) return;
  if (action == "STOP") { // Bridge authenticates; any stop physically halts.
    halt(); searching = false; missionId = id; acknowledge(id, "stopped");
  } else if (action == "START" && digitalRead(STOP_PIN) == HIGH && distanceCm > STOP_DISTANCE_CM && millis()-rangeAt < 500) {
    if (searching && id != missionId) return;
    missionId = id; searching = true; leaseAt = millis(); phase = FORWARD;
    acknowledge(id, "searching");
  } else if (action == "KEEP" && searching && id == missionId) {
    leaseAt = millis(); acknowledge(id, "searching");
  }
}
void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_EN_A, OUTPUT); pinMode(MOTOR_EN_B, OUTPUT);
  pinMode(MOTOR_IN_1, OUTPUT); pinMode(MOTOR_IN_2, OUTPUT);
  pinMode(MOTOR_IN_3, OUTPUT); pinMode(MOTOR_IN_4, OUTPUT);
  pinMode(US_TRIG, OUTPUT); pinMode(US_ECHO, INPUT);
  pinMode(STOP_PIN, INPUT_PULLUP); // Active-low stop input; use a separate physical motor power cutoff.
  halt(); line.reserve(80);
}
void loop() {
  if (digitalRead(STOP_PIN) == LOW) { if (searching) fault("emergency_stop"); else halt(); }
  if (searching && millis()-leaseAt > LEASE_MS) fault("lease");
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { command(line); line = ""; }
    else if (c != '\r') {
      if (line.length() < 80) line += c;
      else { line = ""; fault("protocol"); }
    }
  }
  if (millis()-rangeAt >= RANGE_PERIOD_MS) {
    rangeAt = millis(); distanceCm = measure();
    Serial.print("RANGE "); Serial.println(distanceCm);
    if (searching && distanceCm <= 0) fault("sensor");
  }
  if (!searching) { halt(); return; }
  // Stop before any turn. This reactive baseline has no coverage guarantee,
  // no localization and no ability to detect cliffs or unstable debris.
  if (phase == FORWARD && distanceCm <= STOP_DISTANCE_CM) {
    halt(); phase = BRAKE; phaseAt = millis();
  } else if (phase == BRAKE && millis()-phaseAt >= 300) {
    phase = TURN; phaseAt = millis();
  } else if (phase == TURN && millis()-phaseAt >= 350) {
    halt();
    if (distanceCm > STOP_DISTANCE_CM) phase = FORWARD;
    else { phase = BRAKE; phaseAt = millis(); }
  }
  if (phase == FORWARD) drive(false);
  else if (phase == TURN) drive(true);
  else halt();
}
