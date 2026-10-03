"""Trash can lid servo on a PCA9685 I2C board, and a client that opens it over the network."""
import re
import socket
import subprocess
import sys
import threading
import time

# ---- Easy-to-edit settings ----------------------------------------------
SERVO1_CHANNEL = 0          # PCA9685 channel Servo 1 is plugged into

CENTER_PULSE = 1167         # microseconds at the calibrated center (0 degrees)
US_PER_DEGREE = 11.11

SERVO1_OPEN_ANGLE = 33      # degrees from center; about 1534 us
SERVO1_CLOSED_ANGLE = -57   # degrees from center; about 534 us

HOLD_SECONDS = 5.0          # keep the lid open this long after the last trash reading

PCA9685_ADDRESS = 0x40
I2C_BUS = 1
PWM_FREQUENCY = 50          # Hz
# --------------------------------------------------------------------------

# Never command a pulse outside the calibrated open/closed travel.
MIN_PULSE = CENTER_PULSE + min(SERVO1_OPEN_ANGLE, SERVO1_CLOSED_ANGLE) * US_PER_DEGREE
MAX_PULSE = CENTER_PULSE + max(SERVO1_OPEN_ANGLE, SERVO1_CLOSED_ANGLE) * US_PER_DEGREE

MODE1, PRESCALE, LED0, ALL_LED_OFF_H = 0x00, 0xFE, 0x06, 0xFD
_bus = None


def setup():
    """Configure the PCA9685 for 50 Hz with every output off, so nothing moves yet."""
    global _bus
    try:
        from smbus import SMBus
    except ImportError:
        from smbus2 import SMBus
    _bus = SMBus(I2C_BUS)
    _bus.write_byte_data(PCA9685_ADDRESS, MODE1, 0x10)  # sleep to set frequency
    _bus.write_byte_data(PCA9685_ADDRESS, PRESCALE, round(25_000_000 / (4096 * PWM_FREQUENCY)) - 1)
    # The board keeps the last run's pulses; turn them off until the first command.
    _bus.write_byte_data(PCA9685_ADDRESS, ALL_LED_OFF_H, 0x10)
    _bus.write_byte_data(PCA9685_ADDRESS, MODE1, 0x20)  # wake, auto-increment
    time.sleep(0.01)


def set_servo1_angle(angle):
    """Move Servo 1 to an angle relative to center; it holds that position."""
    pulse_us = min(MAX_PULSE, max(MIN_PULSE, CENTER_PULSE + angle * US_PER_DEGREE))
    count = int(pulse_us * 4096 * PWM_FREQUENCY / 1_000_000)
    reg = LED0 + 4 * SERVO1_CHANNEL
    _bus.write_byte_data(PCA9685_ADDRESS, reg, 0)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 1, 0)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 2, count & 0xFF)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 3, (count >> 8) & 0x0F)
    return pulse_us


def open_servo1():
    return set_servo1_angle(SERVO1_OPEN_ANGLE)


def close_servo1():
    return set_servo1_angle(SERVO1_CLOSED_ANGLE)


class Lid:
    """Opens the lid on trash, then closes it HOLD_SECONDS after the last trash reading."""
    def __init__(self, hold_seconds=HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self.lock = threading.Lock()
        self.timer = None
        self.is_open = False
        try:
            setup()
            self.ready = True
            print(f"Lid servo ready on PCA9685 0x{PCA9685_ADDRESS:02x}, channel {SERVO1_CHANNEL}.", flush=True)
        except Exception as exc:
            self.ready = False
            print(f"Lid servo disabled ({exc}).", file=sys.stderr, flush=True)

    def open(self):
        """Open the lid, or keep it open, for another hold_seconds."""
        if not self.ready:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            if not self.is_open:
                self.is_open = True
                pulse = open_servo1()
                print(f"Trash detected: opening lid ({SERVO1_OPEN_ANGLE:+g} deg, {pulse:.0f} us).", flush=True)
            self.timer = threading.Timer(self.hold_seconds, self.close)
            self.timer.daemon = True
            self.timer.start()

    def close(self):
        if not self.ready:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = None
            if self.is_open:
                self.is_open = False
                pulse = close_servo1()
                print(f"Closing lid ({SERVO1_CLOSED_ANGLE:+g} deg, {pulse:.0f} us).", flush=True)


def broadcast_address():
    """Return the local network's broadcast address, e.g. 192.168.1.255."""
    # macOS refuses 255.255.255.255, so read the Wi-Fi/LAN interface's own one.
    for cmd, pattern in ((["ifconfig"], r"inet (?!127\.)\S+ .*broadcast (\S+)"),
                         (["ip", "-4", "-o", "addr"], r"inet (?!127\.)\S+ brd (\S+)")):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(pattern, out)
        if match:
            return match.group(1)
    return "255.255.255.255"


class RemoteLid:
    """Sends lid commands over UDP to lid_server.py on the Pi."""
    def __init__(self, host=None, port=5006):
        # Without a host, broadcast so any Pi on the same network hears it.
        self.address = (host or broadcast_address(), port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        print(f"Lid commands go to {self.address[0]}{'' if host else ' (whole network)'} on UDP port {port}.", flush=True)

    def send(self, command):
        try:
            self.sock.sendto(command, self.address)
        except OSError as exc:
            print(f"Could not reach lid server: {exc}", file=sys.stderr, flush=True)

    def open(self):
        self.send(b"open")

    def close(self):
        self.send(b"close")
