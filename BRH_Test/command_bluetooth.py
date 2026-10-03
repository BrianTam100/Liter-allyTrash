import serial
import keyboard
import time

# CHANGE THIS to your Outgoing Bluetooth COM port
PORT = 'COM8' 
BAUD = 115200

try:
    print(f"Connecting to Raspberry Pi on {PORT}...")
    bt = serial.Serial(PORT, BAUD, timeout=1)
    print("Connected successfully!")
except Exception as e:
    print(f"Connection failed: {e}")
    exit()

print("Press and hold 'W' to go forward, 'S' to go backward.")
print("Press 'Q' to quit.")

last_state = 'x'

try:
    while True:
        current_state = 'x'
        
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

        if current_state != last_state:
            bt.write(current_state.encode('utf-8'))
            print(f"Sent: {current_state}")
            last_state = current_state

        time.sleep(0.01)
        
except KeyboardInterrupt:
    pass
finally:
    bt.close()