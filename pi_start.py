#!/usr/bin/env python3
"""Run on the rover base's Pi: starts everything driving needs, and restarts any piece that crashes.

    sudo python3 pi_start.py                  # Bluetooth driving (+ camera if pi_camera.py is here)
    sudo python3 pi_start.py --wifi           # drive over Wi-Fi (UDP 5005) instead of Bluetooth
    sudo python3 pi_start.py --no-camera      # skip pi_camera.py

It replaces the separate terminals in docs/demo-runbook.md:
    rfcomm watch hci0  +  motor_control_bluetooth_camera.py  (or motor_control.py with --wifi)
    pi_camera.py (only if it is in this folder)
The lids run on a separate Pi (lid_server.py there), so they aren't started here.

Press Ctrl+C to stop everything: the motors get a stop command.
If something is stuck, run pi_reset.py.
"""
import argparse
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ARDUINO_PORT = "/dev/ttyACM0"
PID_FILE = Path("/run/sortrover-pi.pid")
MAX_BACKOFF = 15            # seconds between restarts of a piece that keeps crashing
HEALTHY_AFTER = 30          # a piece that ran this long resets its restart delay
_print_lock = threading.Lock()


def log(name, message):
    with _print_lock:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {name:>6} | {message}", flush=True)
        except OSError:
            pass  # the SSH terminal went away; keep the rover running anyway


def find_script(name, required=True):
    """Pi copies of the repo keep scripts in the root or in BRH_Test/; accept either."""
    for folder in (HERE, HERE / "BRH_Test"):
        if (folder / name).is_file():
            return str(folder / name)
    if required:
        raise SystemExit(f"Cannot find {name} next to {Path(__file__).name} or in BRH_Test/.")
    return None


def stop_motors():
    """Send the Arduino a stop. Opening the port also resets an Uno, which stops it too."""
    if not Path(ARDUINO_PORT).exists():
        return False  # unplugged, so nothing is driving
    try:
        import serial
        with serial.Serial(ARDUINO_PORT, 115200, timeout=1) as arduino:
            arduino.write(b"x")
            arduino.flush()
        return True
    except Exception as exc:
        log("motors", f"Could not send stop to {ARDUINO_PORT}: {exc}")
        return False


def run_quiet(*cmd):
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def pi_ip():
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout.split()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "<pi-ip>"


def login_user():
    """The user who ran sudo; the camera runs as them so their pip packages and groups apply."""
    name = os.environ.get("SUDO_USER")
    if not name or name == "root":
        return None
    try:
        return pwd.getpwnam(name)
    except KeyError:
        return None


class Piece:
    """One long-running program, restarted with a growing delay whenever it exits."""
    def __init__(self, name, cmd, as_user=None, drives_motors=False):
        self.name, self.cmd, self.as_user, self.drives_motors = name, cmd, as_user, drives_motors
        self.process = None
        self.started = 0.0
        self.backoff = 1
        self.restart_at = 0.0

    def start(self):
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        extra = {}
        if self.as_user:
            user = self.as_user
            env.update(HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name)
            extra = dict(user=user.pw_uid, group=user.pw_gid,
                         extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
        try:
            # Own session, so Ctrl+C reaches only this supervisor and it can stop pieces in order.
            self.process = subprocess.Popen(self.cmd, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                                            start_new_session=True, **extra)
        except OSError as exc:
            log(self.name, f"Could not start: {exc}")
            self.process = None
            self.schedule_restart()
            return
        self.started = time.monotonic()
        log(self.name, f"started (pid {self.process.pid})")
        threading.Thread(target=self.relay_output, args=(self.process,), daemon=True).start()

    def relay_output(self, process):
        for line in process.stdout:
            if line.strip():
                log(self.name, line.rstrip())

    def schedule_restart(self):
        self.restart_at = time.monotonic() + self.backoff
        log(self.name, f"restarting in {self.backoff} s")
        self.backoff = min(MAX_BACKOFF, self.backoff * 2)

    def check(self):
        """Restart this piece if it has exited."""
        if self.process is None:
            if self.restart_at and time.monotonic() >= self.restart_at:
                self.restart_at = 0.0
                self.start()
            return
        code = self.process.poll()
        if code is None:
            return
        log(self.name, f"exited with code {code}")
        self.process = None
        if self.drives_motors:
            stop_motors()  # the bridge may have died mid-drive; don't leave the wheels turning
        if time.monotonic() - self.started > HEALTHY_AFTER:
            self.backoff = 1
        self.schedule_restart()

    def signal(self, sig):
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass

    def wait(self, timeout):
        if not self.process:
            return True
        try:
            self.process.wait(timeout)
            return True
        except subprocess.TimeoutExpired:
            return False


def build_pieces(args):
    user = login_user()
    pieces = []
    if args.wifi:
        pieces.append(Piece("drive", [sys.executable, find_script("motor_control.py")], drives_motors=True))
    else:
        pieces.append(Piece("rfcomm", ["rfcomm", "watch", "hci0"]))
        pieces.append(Piece("drive", [sys.executable, find_script("motor_control_bluetooth_camera.py")],
                            drives_motors=True))
    camera_script = None if args.no_camera else find_script("pi_camera.py", required=False)
    if not args.no_camera and not camera_script:
        log("camera", "pi_camera.py isn't in this folder; skipping the camera.")
    if camera_script:
        camera = [sys.executable, camera_script]
        if args.usb_camera is not None:
            camera += ["--usb", str(args.usb_camera)]
        pieces.append(Piece("camera", camera, as_user=user))
    return pieces


def prepare_bluetooth():
    """Power the adapter on and clear any stale /dev/rfcomm0 left by an earlier run."""
    run_quiet("rfkill", "unblock", "bluetooth")
    run_quiet("rfcomm", "release", "all")
    run_quiet("bluetoothctl", "power", "on")
    run_quiet("bluetoothctl", "pairable", "on")
    # Serial Port Profile; the bluez -C setup in BRH_Test/README.md normally adds it already.
    run_quiet("sdptool", "add", "SP")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wifi", action="store_true", help="drive over Wi-Fi UDP 5005 instead of Bluetooth")
    parser.add_argument("--no-camera", action="store_true", help="don't start pi_camera.py")
    parser.add_argument("--usb-camera", type=int, metavar="INDEX", help="stream this USB webcam, not the Pi camera")
    args = parser.parse_args()

    if os.geteuid() != 0:
        # rfcomm and the Arduino port need root, as in the runbook's "sudo" commands.
        print("Needs root; re-running with sudo...", flush=True)
        os.execvp("sudo", ["sudo", "-E", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text())
            if "pi_start.py" not in Path(f"/proc/{old}/cmdline").read_bytes().decode(errors="replace"):
                raise ValueError("pid reused by another program")
            raise SystemExit(f"pi_start.py is already running (pid {old}). Run pi_reset.py to stop it first.")
        except (ValueError, OSError):
            pass  # stale file from a crash
    PID_FILE.write_text(str(os.getpid()))

    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    # Keep driving if the SSH session drops; pi_reset.py stops it from a new session.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    pieces = build_pieces(args)
    if not Path(ARDUINO_PORT).exists():
        log("drive", f"{ARDUINO_PORT} not found; is the Arduino plugged in? Will keep retrying.")
    if not args.wifi:
        prepare_bluetooth()

    ip = pi_ip()
    log("pi", f"SortRover base starting on {ip} ({'Wi-Fi' if args.wifi else 'Bluetooth'} driving)")
    if any(piece.name == "camera" for piece in pieces):
        log("pi", f"Camera for the laptop: web_server.py ... --camera http://{ip}:8080/stream.mjpg")
    if args.wifi:
        log("pi", f"and set PI_IP={ip} in BRH_Test/.env, Connection = Wi-Fi on Rover controls")
    log("pi", "Press Ctrl+C to stop everything.")

    try:
        for piece in pieces:
            piece.start()
        while not stopping.wait(0.5):
            for piece in pieces:
                piece.check()
    finally:
        log("pi", "Stopping...")
        # Reverse order: camera first, then the drive bridge, then rfcomm.
        # SIGINT lets each script run its own cleanup (motors get "x").
        for piece in reversed(pieces):
            piece.signal(signal.SIGINT)
        for piece in reversed(pieces):
            if not piece.wait(5):
                piece.signal(signal.SIGTERM)
                if not piece.wait(2):
                    piece.signal(signal.SIGKILL)
        stop_motors()
        if not args.wifi:
            run_quiet("rfcomm", "release", "all")
        PID_FILE.unlink(missing_ok=True)
        log("pi", "Stopped.")


if __name__ == "__main__":
    main()
