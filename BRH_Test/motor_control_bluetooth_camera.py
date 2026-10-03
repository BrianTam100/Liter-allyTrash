import serial
import time

ARDUINO_PORT = '/dev/ttyACM0'
BT_PORT = '/dev/rfcomm0'

# Connect to Arduino
try:
    arduino = serial.Serial(ARDUINO_PORT, 115200, timeout=1)
    time.sleep(2)
    print(f"Connected to Arduino on {ARDUINO_PORT}")
except Exception as e:
    print(f"Arduino error: {e}")
    exit()

# Wait for Windows to connect via Bluetooth
print("Waiting for Windows Bluetooth connection...")
while True:
    try:
        bt = serial.Serial(BT_PORT, 115200, timeout=0.1)
        print("Bluetooth connected! Ready to drive.")
        break
    except serial.SerialException:
        time.sleep(1) # Keep trying until /dev/rfcomm0 is created

try:
    while True:
        if bt.in_waiting > 0:
            # Read all available bytes in the buffer at once 
            data = bt.read(bt.in_waiting)
            
            # Forward the raw bytes directly to the Arduino
            arduino.write(data)
            
            # Print to terminal so you can see it working
            try:
                text = data.decode('utf-8').strip()
                if text:
                    print(f"Forwarded: {text}")
            except UnicodeDecodeError:
                pass
                
except KeyboardInterrupt:
    arduino.write(b'x')
    bt.close()
    arduino.close()