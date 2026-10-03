#include <AccelStepper.h>

const int enPin = 8;

// CNC shield axes. These labels match the working W/S mix:
// X = front-left, Y = front-right, Z = back-left, A = back-right.
AccelStepper stepperX(AccelStepper::DRIVER, 2, 5);
AccelStepper stepperY(AccelStepper::DRIVER, 3, 6);
AccelStepper stepperZ(AccelStepper::DRIVER, 4, 7);
AccelStepper stepperA(AccelStepper::DRIVER, 9, 10);

const float maxSpeed = 1000.0;

// +1 means setSpeed(+maxSpeed) drives that motor toward robot-forward.
// Copied from the mix that already worked for W (X+, Y-, Z+, A+).
const float DIR_X = 1.0;
const float DIR_Y = -1.0;
const float DIR_Z = 1.0;
const float DIR_A = 1.0;

void applyMecanum(float vx, float vyRight, float yawCCW)
{
  // vx: forward, vyRight: strafe right, yawCCW: spin left.
  float fl = vx - vyRight - yawCCW;
  float fr = vx + vyRight + yawCCW;
  float bl = vx + vyRight - yawCCW;
  float br = vx - vyRight + yawCCW;

  float peak = fabs(fl);
  if (fabs(fr) > peak) peak = fabs(fr);
  if (fabs(bl) > peak) peak = fabs(bl);
  if (fabs(br) > peak) peak = fabs(br);
  if (peak > 1.0) {
    fl /= peak;
    fr /= peak;
    bl /= peak;
    br /= peak;
  }

  stepperX.setSpeed(DIR_X * fl * maxSpeed);
  stepperY.setSpeed(DIR_Y * fr * maxSpeed);
  stepperZ.setSpeed(DIR_Z * bl * maxSpeed);
  stepperA.setSpeed(DIR_A * br * maxSpeed);
}

void setup()
{
  pinMode(enPin, OUTPUT);
  digitalWrite(enPin, LOW);

  stepperX.setMaxSpeed(maxSpeed);
  stepperY.setMaxSpeed(maxSpeed);
  stepperZ.setMaxSpeed(maxSpeed);
  stepperA.setMaxSpeed(maxSpeed);

  Serial.begin(115200);
  Serial.setTimeout(10);
}

void loop()
{
  if (Serial.available() > 0)
  {
    char incomingChar = Serial.peek();

    if (isAlpha(incomingChar)) {
      char cmd = Serial.read();

      if (cmd == 'w') {
        applyMecanum(1, 0, 0);
      }
      else if (cmd == 's') {
        applyMecanum(-1, 0, 0);
      }
      else if (cmd == 'a') {
        // Spin in place. Old A/D reversed front vs rear, which jammed the X wheel.
        applyMecanum(0, 0, 1);
      }
      else if (cmd == 'd') {
        applyMecanum(0, 0, -1);
      }
      else if (cmd == 'x') {
        applyMecanum(0, 0, 0);
      }
    }
    else if (isDigit(incomingChar) || incomingChar == '-') {
      float angle = Serial.parseFloat();
      float rad = angle * (PI / 180.0);
      // Unit circle: 90 = forward, 0 = right, 180 = left, 270 = back.
      applyMecanum(sin(rad), cos(rad), 0);
    }
    else {
      Serial.read();
    }
  }

  stepperX.runSpeed();
  stepperY.runSpeed();
  stepperZ.runSpeed();
  stepperA.runSpeed();
}
