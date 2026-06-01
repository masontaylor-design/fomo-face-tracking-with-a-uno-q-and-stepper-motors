// ================================================================
//  Face Tracker Motor Controller — C++ Sketch (MCU side)
//  Arduino UNO Q — App Lab App
// ================================================================
//  Receives pan/tilt speed commands from Python via Bridge.
//  Drives two A4988 stepper motors non-blocking.
//
//  A4988 Wiring:
//    STEP_M1 = D8   DIR_M1 = D9    (Motor 1 — TILT / Y axis)
//    STEP_M2 = D10  DIR_M2 = D11   (Motor 2 — PAN  / X axis)
//    EN      = D7   (active LOW, shared enable)
// ================================================================

#include "Arduino_RouterBridge.h"

#define STEP_M1  8
#define DIR_M1   9
#define STEP_M2  10
#define DIR_M2   11
#define EN       7

volatile int motor1Speed = 0;   // tilt
volatile int motor2Speed = 0;   // pan

unsigned long lastStep1 = 0, lastStep2 = 0, lastCmdMs = 0;
#define TIMEOUT_MS 1000

int speedToDelay(int speed) {
  int a = abs(speed);
  if (a < 5) return 0;
  return map(a, 5, 100, 3000, 300);
}

void set_motors(int pan, int tilt) {
  motor2Speed = constrain(pan,  -100, 100);
  motor1Speed = constrain(tilt, -100, 100);
  lastCmdMs = millis();
}

void stop_motors() {
  motor1Speed = 0;
  motor2Speed = 0;
  lastCmdMs = millis();
}

void motorSelfTest() {
  digitalWrite(DIR_M1, HIGH);
  for (int i = 0; i < 200; i++) { digitalWrite(STEP_M1, HIGH); delayMicroseconds(50); digitalWrite(STEP_M1, LOW); delayMicroseconds(900); }
  digitalWrite(DIR_M2, HIGH);
  for (int i = 0; i < 200; i++) { digitalWrite(STEP_M2, HIGH); delayMicroseconds(50); digitalWrite(STEP_M2, LOW); delayMicroseconds(900); }
}

void setup() {
  pinMode(STEP_M1, OUTPUT); pinMode(DIR_M1, OUTPUT);
  pinMode(STEP_M2, OUTPUT); pinMode(DIR_M2, OUTPUT);
  pinMode(EN, OUTPUT); digitalWrite(EN, LOW);
  motorSelfTest();
  Bridge.begin();
  Bridge.provide("set_motors",  set_motors);
  Bridge.provide("stop_motors", stop_motors);
  lastCmdMs = millis();
}

void loop() {
  Bridge.update();
  if ((millis() - lastCmdMs) > TIMEOUT_MS) { motor1Speed = 0; motor2Speed = 0; }
  unsigned long now = micros();
  int d1 = speedToDelay(motor1Speed);
  if (d1 > 0 && (now - lastStep1) >= (unsigned long)d1) {
    digitalWrite(DIR_M1, motor1Speed > 0 ? HIGH : LOW);
    digitalWrite(STEP_M1, HIGH); delayMicroseconds(50); digitalWrite(STEP_M1, LOW);
    lastStep1 = now;
  }
  int d2 = speedToDelay(motor2Speed);
  if (d2 > 0 && (now - lastStep2) >= (unsigned long)d2) {
    digitalWrite(DIR_M2, motor2Speed > 0 ? HIGH : LOW);
    digitalWrite(STEP_M2, HIGH); delayMicroseconds(50); digitalWrite(STEP_M2, LOW);
    lastStep2 = now;
  }
}
