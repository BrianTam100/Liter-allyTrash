"""Run on the Pi: nudge each lid servo and save its open and closed positions.

Saved values go to servo_calibration.json next to this file, which the lid code
reads, so each can only needs to be calibrated once.
"""
import json
from pathlib import Path
import time

from smbus import SMBus

# ==========================
ADDR = 0x40
I2C_BUS = 1

CHANNELS = [0, 3]          # one servo per trash can
START_PULSE = 1167         # assumed position before the first move if nothing is saved
US_PER_DEGREE = 11.11

MIN_PULSE = 350
MAX_PULSE = 2500
# ==========================

CALIBRATION = Path(__file__).resolve().parent / "servo_calibration.json"
MODE1, PRESCALE, LED0 = 0x00, 0xFE, 0x06
ALL_LED_OFF_H = 0xFD

bus = SMBus(I2C_BUS)


def setup():
    """Configure 50 Hz with every output off, so nothing moves until a command."""
    bus.write_byte_data(ADDR, MODE1, 0x10)
    bus.write_byte_data(ADDR, PRESCALE, 121)
    bus.write_byte_data(ADDR, ALL_LED_OFF_H, 0x10)
    bus.write_byte_data(ADDR, MODE1, 0x20)
    time.sleep(0.01)


def set_servo(channel, pulse_us):
    count = int(round(pulse_us * 4096 / 20000))
    reg = LED0 + 4 * channel
    bus.write_byte_data(ADDR, reg, 0)
    bus.write_byte_data(ADDR, reg + 1, 0)
    bus.write_byte_data(ADDR, reg + 2, count & 0xFF)
    bus.write_byte_data(ADDR, reg + 3, (count >> 8) & 0x0F)


def release(channel):
    """Stop the pulses so the servo goes limp."""
    bus.write_byte_data(ADDR, LED0 + 4 * channel + 3, 0x10)


def load():
    try:
        return json.loads(CALIBRATION.read_text())
    except (OSError, ValueError):
        return {}


def save(calibration):
    CALIBRATION.write_text(json.dumps(calibration, indent=2) + "\n")


def show(calibration):
    print("\nSaved calibration:")
    for channel in CHANNELS:
        saved = calibration.get(str(channel), {})
        print(f"  CH {channel}: open = {saved.get('open_us', '—')} us, closed = {saved.get('closed_us', '—')} us")


HELP = """
  10 / -5     nudge by degrees (from the current position)
  p 1500      go to an exact pulse in microseconds
  o           save the current position as OPEN
  c           save the current position as CLOSED
  to / tc     test: move to the saved open / closed position
  off         release the servo (stop holding)
  b           back to channel selection
"""


def calibrate(channel, calibration):
    saved = calibration.setdefault(str(channel), {})
    pulse = saved.get("closed_us", START_PULSE)
    known = "closed_us" in saved
    print(f"\nCHANNEL {channel} SELECTED" + HELP)
    if not known:
        print(f"Its real position is unknown: the first move starts from {START_PULSE} us.")
    while True:
        command = input(f"CH {channel} [{pulse:.0f} us]: ").strip().lower()
        try:
            if command == "b":
                return
            if command in ("o", "c"):
                key = "open_us" if command == "o" else "closed_us"
                saved[key] = round(pulse)
                save(calibration)
                print(f"Saved CH {channel} {'OPEN' if command == 'o' else 'CLOSED'} = {round(pulse)} us")
                continue
            if command in ("to", "tc"):
                key = "open_us" if command == "to" else "closed_us"
                if key not in saved:
                    print("Nothing saved for that yet.")
                    continue
                target = saved[key]
            elif command == "off":
                release(channel)
                print("Released; the servo is no longer holding.")
                continue
            elif command.startswith("p "):
                target = float(command[2:])
            else:
                target = pulse + float(command) * US_PER_DEGREE
        except ValueError:
            print("Enter degrees, p <us>, o, c, to, tc, off or b.")
            continue
        if not MIN_PULSE <= target <= MAX_PULSE:
            target = min(MAX_PULSE, max(MIN_PULSE, target))
            print(f"Limited to {target:.0f} us.")
        set_servo(channel, target)
        print(f"Moved {(target - pulse) / US_PER_DEGREE:+.1f} deg -> {target:.0f} us")
        pulse = target


def main():
    setup()
    calibration = load()
    print("Lid servo calibration (PCA9685)")
    print("-------------------------------")
    show(calibration)
    while True:
        choice = input(f"\nChannel {CHANNELS} (s = show saved, q = quit): ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            show(calibration)
            continue
        try:
            channel = int(choice)
            if not 0 <= channel <= 15:
                raise ValueError
        except ValueError:
            print("Enter a channel number 0-15, s or q.")
            continue
        calibrate(channel, calibration)
    show(calibration)
    print(f"Saved in {CALIBRATION}")


if __name__ == "__main__":
    main()
