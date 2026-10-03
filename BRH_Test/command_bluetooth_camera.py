import serial
import keyboard
import time
import cv2
import mediapipe as mp
import math

# CHANGE THIS to your Outgoing Bluetooth COM port
PORT = 'COM8' 
BAUD = 115200

# 1. Initialize Bluetooth
try:
    print(f"Connecting to Raspberry Pi on {PORT}...")
    bt = serial.Serial(PORT, BAUD, timeout=1)
    print("Connected successfully!")
except Exception as e:
    print(f"Connection failed: {e}")
    exit()

# 2. Initialize Camera & MediaPipe
print("Initializing Camera...")
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
mp_draw = mp.solutions.drawing_utils
cap = cv2.VideoCapture(0)

print("Ready! Use WASD to drive, or hold your hand up to the camera.")
print("Press 'Q' to quit.")

last_state = 'x'

try:
    while True:
        # Read camera frame every loop so the video feed doesn't freeze
        success, img = cap.read()
        if not success:
            continue
            
        img = cv2.flip(img, 1) # Mirror image
        
        current_state = 'x' # Default to stop

        # --- KEYBOARD CHECK (Highest Priority) ---
        if keyboard.is_pressed('w') or keyboard.is_pressed('up'):
            current_state = 'w'
        elif keyboard.is_pressed('a') or keyboard.is_pressed('left'):
            current_state = 'a'
        elif keyboard.is_pressed('d') or keyboard.is_pressed('right'):
            current_state = 'd'
        elif keyboard.is_pressed('s') or keyboard.is_pressed('down'):
            current_state = 's'
        elif keyboard.is_pressed('q'):
            bt.write(b'x')
            print("Exiting...")
            break

        # --- CAMERA CHECK (Only if no keys are pressed) ---
        if current_state == 'x':
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = hands.process(img_rgb)

            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    mp_draw.draw_landmarks(img, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                    wrist = hand_landmarks.landmark[0]
                    index_tip = hand_landmarks.landmark[8]

                    dx = index_tip.x - wrist.x
                    dy = index_tip.y - wrist.y 

                    angle_rad = math.atan2(-dy, dx)
                    angle_deg = math.degrees(angle_rad)

                    if angle_deg < 0:
                        angle_deg += 360

                    # Round to the nearest 5 degrees to prevent serial buffer flooding & stutter
                    final_angle = int(round(angle_deg / 5.0) * 5)
                    if final_angle == 360: final_angle = 0
                    
                    # Format as string with newline for Arduino's parseFloat()
                    current_state = f"{final_angle}\n"
                    
                    cv2.putText(img, f"Angle: {final_angle}", (50, 50), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            else:
                cv2.putText(img, "STOP", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        # --- SEND DATA (Only if the state/angle changed) ---
        if current_state != last_state:
            bt.write(current_state.encode('utf-8'))
            # Only print if it's a major change so the console doesn't become unreadable
            print(f"Sent: {current_state.strip()}") 
            last_state = current_state

        # Show the camera feed
        cv2.imshow("Hand Joystick", img)
        
        # Required to update the OpenCV window
        if cv2.waitKey(1) & 0xFF == ord('q'):
            bt.write(b'x')
            break

        time.sleep(0.01)

except KeyboardInterrupt:
    bt.write(b'x')
finally:
    cap.release()
    cv2.destroyAllWindows()
    bt.close()