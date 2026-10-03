import socket
import keyboard
import time

# Your Raspberry Pi's IP Address
PI_IP = "172.20.8.62" 
UDP_PORT = 5005

print(f"Targeting Raspberry Pi at {PI_IP}:{UDP_PORT}")
print("Press and hold 'W' to go forward, 'S' to go backward.")
print("Press 'Q' to quit.")

# Set up the network sender
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
last_state = 'x'

try:
    while True:
        current_state = 'x' # Default to stop

        if keyboard.is_pressed('w') or keyboard.is_pressed('up'):
            current_state = 'w'
        elif keyboard.is_pressed('a') or keyboard.is_pressed('left'):
            current_state = 'a'
        elif keyboard.is_pressed('d') or keyboard.is_pressed('right'):
            current_state = 'd'
        elif keyboard.is_pressed('s') or keyboard.is_pressed('down'):
            current_state = 's'
        elif keyboard.is_pressed('q'):
            print("Exiting...")
            sock.sendto(b'x', (PI_IP, UDP_PORT)) # Send a stop command before quitting
            break

        # Send an update over Wi-Fi only if the state changed
        if current_state != last_state:
            sock.sendto(current_state.encode('utf-8'), (PI_IP, UDP_PORT))
            print(f"Sent over Wi-Fi: {current_state}")
            last_state = current_state

        time.sleep(0.05)
        
except KeyboardInterrupt:
    pass
finally:
    sock.close()