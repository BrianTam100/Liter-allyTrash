"""Trash can lid servos on a PCA9685 I2C board, and a client that opens them over the network."""
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

# ---- Easy-to-edit settings ----------------------------------------------
# Which PCA9685 channel opens for each kind of item.
CANS = {"Trash": 0, "Recyclable": 3}

# Calibrated lid positions in microseconds (found with calibrate_lids.py).
# servo_calibration.json next to this file overrides these when present.
CALIBRATION = {
    0: {"open_us": 1611, "closed_us": 534},   # trash can
    3: {"open_us": 1722, "closed_us": 823},   # recycling can
}

HOLD_SECONDS = 5.0          # keep a lid open this long after the last matching reading

PCA9685_ADDRESS = 0x40
I2C_BUS = 1
PWM_FREQUENCY = 50          # Hz
# --------------------------------------------------------------------------

CALIBRATION_FILE = Path(__file__).resolve().parent / "servo_calibration.json"
MODE1, PRESCALE, LED0, ALL_LED_OFF_H = 0x00, 0xFE, 0x06, 0xFD
_bus = None


def load_calibration():
    """Return {channel: {"open_us", "closed_us"}}, preferring servo_calibration.json."""
    calibration = {channel: dict(values) for channel, values in CALIBRATION.items()}
    try:
        saved = json.loads(CALIBRATION_FILE.read_text())
    except (OSError, ValueError):
        return calibration
    for channel, values in saved.items():
        if {"open_us", "closed_us"} <= set(values):
            calibration[int(channel)] = {"open_us": values["open_us"], "closed_us": values["closed_us"]}
    return calibration


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


def set_pulse(channel, pulse_us, calibration):
    """Move a lid servo and hold it there, never past its calibrated open/closed travel."""
    low, high = sorted((calibration[channel]["open_us"], calibration[channel]["closed_us"]))
    pulse_us = min(high, max(low, pulse_us))
    count = int(round(pulse_us * 4096 * PWM_FREQUENCY / 1_000_000))
    reg = LED0 + 4 * channel
    _bus.write_byte_data(PCA9685_ADDRESS, reg, 0)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 1, 0)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 2, count & 0xFF)
    _bus.write_byte_data(PCA9685_ADDRESS, reg + 3, (count >> 8) & 0x0F)
    return pulse_us


class Lid:
    """Opens the can for each detected item, then closes it HOLD_SECONDS after the last reading."""
    def __init__(self, hold_seconds=HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self.calibration = load_calibration()
        self.lock = threading.Lock()
        self.timers = {}
        self.open_cans = set()
        try:
            setup()
            self.ready = True
            print(f"Lid servos ready on PCA9685 0x{PCA9685_ADDRESS:02x}:", flush=True)
            for name, channel in CANS.items():
                values = self.calibration[channel]
                print(f"  {name}: channel {channel}, open {values['open_us']} us, closed {values['closed_us']} us",
                      flush=True)
        except Exception as exc:
            self.ready = False
            print(f"Lid servos disabled ({exc}).", file=sys.stderr, flush=True)

    def open(self, can="Trash"):
        """Open one can's lid, or keep it open, for another hold_seconds."""
        if not self.ready or can not in CANS:
            return
        with self.lock:
            if self.timers.get(can):
                self.timers[can].cancel()
            if can not in self.open_cans:
                self.open_cans.add(can)
                channel = CANS[can]
                pulse = set_pulse(channel, self.calibration[channel]["open_us"], self.calibration)
                print(f"{can} detected: opening channel {channel} ({pulse:.0f} us).", flush=True)
            self.timers[can] = threading.Timer(self.hold_seconds, self.close, args=(can,))
            self.timers[can].daemon = True
            self.timers[can].start()

    def close(self, can=None):
        """Close one can's lid, or every open lid when no can is given."""
        if not self.ready:
            return
        with self.lock:
            for name in [can] if can else list(CANS):
                if self.timers.get(name):
                    self.timers.pop(name).cancel()
                if name in self.open_cans:
                    self.open_cans.discard(name)
                    channel = CANS[name]
                    pulse = set_pulse(channel, self.calibration[channel]["closed_us"], self.calibration)
                    print(f"Closing {name} lid, channel {channel} ({pulse:.0f} us).", flush=True)


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

    def open(self, can="Trash"):
        self.send(b"open " + can.encode())

    def close(self, can=None):
        self.send(b"close" + (b" " + can.encode() if can else b""))
