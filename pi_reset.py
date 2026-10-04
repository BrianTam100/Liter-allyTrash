#!/usr/bin/env python3
"""Run on the rover base's Pi: stops every rover script and resets the connections, for when something is stuck.

    sudo python3 pi_reset.py              # stop everything, stop motors, reset Bluetooth
    sudo python3 pi_reset.py --start      # ...then start everything again with pi_start.py
    sudo python3 pi_reset.py --start --wifi --no-camera   # extra options go to pi_start.py
    sudo python3 pi_reset.py --restart-wifi               # also restart Wi-Fi (drops SSH briefly!)

What it does:
  1. Stops pi_start.py and any rover script started by hand (drive bridges, pi_camera.py,
     rfcomm watch).
  2. Sends the Arduino a stop.
  3. Releases /dev/rfcomm0, restarts the Bluetooth service, and makes the Pi pairable and
     discoverable again.
  4. Checks the ports (UDP 5005, TCP 8080) are free.

The lids run on a separate Pi; this doesn't touch them.

After a reset, press Connect rover again on the laptop. If Windows still can't connect,
remove and re-pair the Pi in Windows Bluetooth settings.
"""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ARDUINO_PORT = "/dev/ttyACM0"
PID_FILE = Path("/run/sortrover-pi.pid")
ROVER_SCRIPTS = ("pi_start.py", "motor_control_bluetooth_camera.py", "motor_control.py", "pi_camera.py")


def step(message):
    print(f"\n== {message}", flush=True)


def run(*cmd, quiet=False):
    """Run a command, print what failed, and return True if it worked."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        if not quiet:
            print(f"   {' '.join(cmd)}: {exc}", flush=True)
        return False
    if result.returncode != 0 and not quiet:
        print(f"   {' '.join(cmd)} failed: {(result.stderr or result.stdout).strip()}", flush=True)
    return result.returncode == 0


def rover_processes():
    """Return {pid: command line} for every rover script and rfcomm watch, except this one."""
    me = {os.getpid(), os.getppid()}
    found = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in me:
            continue
        try:
            args = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        names = [Path(arg).name for arg in args if arg]
        if not names:
            continue
        # Skip "sudo python3 x.py" wrappers; sudo passes our signals on to the real process.
        if names[0] == "sudo":
            continue
        is_rfcomm = names[0] == "rfcomm" and "watch" in names
        is_script = names[0].startswith("python") and any(name in ROVER_SCRIPTS for name in names[1:3])
        if is_rfcomm or is_script:
            found[int(entry.name)] = " ".join(names)
    return found


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def wait_gone(pids, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pids = [pid for pid in pids if alive(pid)]
        if not pids:
            return []
        time.sleep(0.2)
    return [pid for pid in pids if alive(pid)]


def stop_programs():
    step("Stopping rover programs")
    # The supervisor first: it stops its own pieces in order and lets them clean up.
    try:
        supervisor = int(PID_FILE.read_text())
        if alive(supervisor):
            print(f"   pi_start.py (pid {supervisor})", flush=True)
            os.kill(supervisor, signal.SIGTERM)
            if wait_gone([supervisor], 12):
                os.kill(supervisor, signal.SIGKILL)
    except (OSError, ValueError):
        pass
    PID_FILE.unlink(missing_ok=True)

    # Then anything still running, including scripts started by hand in other terminals.
    leftovers = rover_processes()
    if not leftovers:
        print("   nothing else running", flush=True)
        return
    for pid, cmd in leftovers.items():
        print(f"   {cmd} (pid {pid})", flush=True)
    # SIGINT first: the scripts treat it like Ctrl+C (motors get "x").
    for sig, seconds in ((signal.SIGINT, 4), (signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        for pid in leftovers:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        remaining = wait_gone(list(leftovers), seconds)
        if not remaining:
            return
        leftovers = {pid: leftovers[pid] for pid in remaining}
    for pid, cmd in leftovers.items():
        print(f"   could not stop {cmd} (pid {pid})", flush=True)


def stop_motors():
    step("Stopping the motors")
    if not Path(ARDUINO_PORT).exists():
        print(f"   {ARDUINO_PORT} not found; is the Arduino plugged in?", flush=True)
        return
    try:
        import serial
        # Opening the port resets an Uno (which stops it); the "x" covers boards that don't reset.
        with serial.Serial(ARDUINO_PORT, 115200, timeout=1) as arduino:
            time.sleep(2)
            arduino.write(b"x")
            arduino.flush()
        print(f"   sent stop to {ARDUINO_PORT}", flush=True)
    except Exception as exc:
        print(f"   could not reach {ARDUINO_PORT}: {exc}", flush=True)


def reset_bluetooth():
    step("Resetting Bluetooth")
    run("rfcomm", "release", "all", quiet=True)
    run("rfkill", "unblock", "bluetooth")
    if run("systemctl", "restart", "bluetooth"):
        print("   bluetooth service restarted", flush=True)
    # The adapter takes a moment to come back after the restart.
    for _ in range(20):
        if run("bluetoothctl", "show", quiet=True):
            break
        time.sleep(0.5)
    time.sleep(1)
    run("sdptool", "add", "SP", quiet=True)  # Serial Port Profile, in case bluez -C isn't set up
    for setting in (("power", "on"), ("pairable", "on"), ("discoverable", "on")):
        if run("bluetoothctl", *setting):
            print(f"   {' '.join(setting)}", flush=True)


def restart_wifi():
    step("Restarting Wi-Fi (SSH will drop for a few seconds)")
    if run("nmcli", "radio", "wifi", "off", quiet=True):
        time.sleep(2)
        run("nmcli", "radio", "wifi", "on")
    else:
        run("rfkill", "block", "wifi")
        time.sleep(2)
        run("rfkill", "unblock", "wifi")
    time.sleep(8)
    try:
        ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        ip = ""
    print(f"   IP address: {ip or 'none yet; check the Wi-Fi network'}", flush=True)


def check_ports():
    step("Checking ports")
    for kind, port, what in ((socket.SOCK_DGRAM, 5005, "Wi-Fi drive"), (socket.SOCK_STREAM, 8080, "camera")):
        sock = socket.socket(socket.AF_INET, kind)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            print(f"   {port} ({what}) free", flush=True)
        except OSError:
            print(f"   {port} ({what}) STILL IN USE; check: sudo ss -lunpt | grep {port}", flush=True)
        finally:
            sock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", action="store_true", help="start everything again with pi_start.py afterwards")
    parser.add_argument("--restart-wifi", action="store_true", help="also restart Wi-Fi (drops SSH briefly)")
    args, start_args = parser.parse_known_args()
    if start_args and not args.start:
        parser.error(f"unrecognized arguments: {' '.join(start_args)} (pi_start.py options need --start)")

    if os.geteuid() != 0:
        print("Needs root; re-running with sudo...", flush=True)
        os.execvp("sudo", ["sudo", "-E", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    stop_programs()
    stop_motors()
    reset_bluetooth()
    if args.restart_wifi:
        restart_wifi()
    check_ports()

    if args.start:
        step("Starting pi_start.py")
        os.execv(sys.executable, [sys.executable, str(HERE / "pi_start.py"), *start_args])
    print("\nReset done. Start again with:  sudo python3 pi_start.py", flush=True)
    print("Then press Connect rover on the laptop.", flush=True)


if __name__ == "__main__":
    main()
