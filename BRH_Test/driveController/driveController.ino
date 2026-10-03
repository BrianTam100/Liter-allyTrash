#include <AccelStepper.h>

const int enPin = 8;  

// Initialize steppers (DRIVER mode, Step Pin, Dir Pin)
AccelStepper stepperX(AccelStepper::DRIVER, 2, 5);  // X-Axis (Motor 1)
AccelStepper stepperY(AccelStepper::DRIVER, 3, 6);  // Y-Axis (Motor 2)
AccelStepper stepperZ(AccelStepper::DRIVER, 4, 7);  // Z-Axis (Motor 3)
AccelStepper stepperA(AccelStepper::DRIVER, 9, 10); // A-Axis (Motor 4)

float maxSpeed = 1000.0; // Maximum steps per second

void setup() 
{
  pinMode(enPin, OUTPUT);
  digitalWrite(enPin, LOW); 

  // Configure max speeds for all motors
  stepperX.setMaxSpeed(maxSpeed);
  stepperY.setMaxSpeed(maxSpeed);
  stepperZ.setMaxSpeed(maxSpeed);
  stepperA.setMaxSpeed(maxSpeed);

  // Note: Depending on how your motors are mounted, 
  // you may need to invert the direction of the right-side motors so they spin "forward".
  // Uncomment these if your rover spins in a circle when told to go straight:
  // stepperY.setPinsInverted(true, false, false);
  // stepperA.setPinsInverted(true, false, false);
  Serial.begin(115200);
}

void loop() 
{
  if (Serial.available() > 0) 
  {
    char incomingChar = Serial.peek(); 
    
    // WASD/Arrow Key Control  
    if (isAlpha(incomingChar)) {
      char cmd = Serial.read();
      
      if (cmd == 'w') {
        stepperX.setSpeed(maxSpeed);
        stepperY.setSpeed(-maxSpeed);
        stepperZ.setSpeed(maxSpeed);
        stepperA.setSpeed(maxSpeed);
      } 
      else if (cmd == 'a') {
        stepperX.setSpeed(-maxSpeed);
        stepperY.setSpeed(maxSpeed);
        stepperZ.setSpeed(maxSpeed);
        stepperA.setSpeed(maxSpeed);
      } 
      else if (cmd == 'd') {
        stepperX.setSpeed(maxSpeed);
        stepperY.setSpeed(-maxSpeed);
        stepperZ.setSpeed(-maxSpeed);
        stepperA.setSpeed(-maxSpeed);
      } 
      else if (cmd == 's') {
        stepperX.setSpeed(-maxSpeed);
        stepperY.setSpeed(maxSpeed);
        stepperZ.setSpeed(-maxSpeed);
        stepperA.setSpeed(-maxSpeed);
      }
      else if (cmd == 'x') {
        // Stop the rover
        stepperX.setSpeed(0);
        stepperY.setSpeed(0);
        stepperZ.setSpeed(0);
        stepperA.setSpeed(0);
      }
    } 
    // MECANUM ANGLE CONTROL
    else if (isDigit(incomingChar) || incomingChar == '-') {
      float angle = Serial.parseFloat(); // Parses the full number
      
      float rad = angle * (PI / 180.0);
      
      // Calculate speeds based on mecanum wheel kinematics
      float speedFL = sin(rad + PI / 4.0); 
      float speedFR = cos(rad + PI / 4.0); 
      float speedBL = cos(rad + PI / 4.0); 
      float speedBR = sin(rad + PI / 4.0);

      // Apply the speeds. 
      // Note: Depending on which axis (X,Y,Z,A) correlates to which wheel 
      // (FL, FR, BL, BR), you may need to shuffle these assignments.
      stepperX.setSpeed(speedFL * maxSpeed);
      stepperY.setSpeed(speedFR * maxSpeed);
      stepperZ.setSpeed(speedBL * maxSpeed);
      stepperA.setSpeed(speedBR * maxSpeed);
    } 
    else {
      Serial.read(); 
    }
  }

  // Execute steps if required. NEVER put a delay() in this loop!
  stepperX.runSpeed();
  stepperY.runSpeed();
  stepperZ.runSpeed();
  stepperA.runSpeed();
}