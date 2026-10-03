import serial
import socket
import time

# Arduino USB Port Configuration
PORT = '/dev/ttyACM0' 
BAUD = 9600

# Network Configuration
UDP_IP = "0.0.0.0" # This means "Listen on all network connections"
UDP_PORT = 5005    # The "channel" we are communicating on

try:
    # Connect to Arduino
    ser = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(2) # Give the Arduino 2 seconds to reboot after connecting
    print(f"Connected to Arduino on {PORT}!")
except Exception as e:
    print(f"Serial Error: {e}")
    exit()

# Set up the Wi-Fi Listener
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
print(f"Listening for PC keyboard commands on port {UDP_PORT}...")

last_state = 'x'

try:
    while True:
        # Wait until a message is received over Wi-Fi
        data, addr = sock.recvfrom(1024) 
        command = data.decode('utf-8').strip()

        # If it's a valid command, send it to the Arduino
        if command in ['w', 'a', 'd', 's', 'x']:
            if command != last_state:
                ser.write(command.encode('utf-8'))
                print(f"Relayed to Arduino: {command}")
                last_state = command
                
except KeyboardInterrupt:
    print("\nStopping...")
    ser.write(b'x')
    ser.close()
    sock.close()