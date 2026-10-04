#!/usr/bin/env python3
"""Run on the lid Pi (the one on the trash cans with the camera): starts everything it runs.

    python3 start_lid_pi.py              # start lid_server.py + pi_camera.py; Ctrl+C stops both, closes lids
    python3 start_lid_pi.py --no-camera  # lids only (also: --no-lid, --usb-camera 0)
    python3 end_lid_pi.py                # from any terminal: stop everything and close the lids

Keep both files next to lid.py, lid_server.py and pi_camera.py. Lids run with servo-env's Python when
it exists (that's where smbus is installed); the camera uses the system Python (picamera2).
Crashed pieces restart by themselves. It keeps running if the SSH session drops.
"""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
PID_FILE = Path("/tmp/sortrover-lid-pi.pid")
OUR_SCRIPTS = ("start_lid_pi.py", "lid_server.py", "pi_camera.py", "calibrate_lids.py", "servo_test.py")
MAX_BACKOFF = 15            # seconds between restarts of a piece that keeps crashing
HEALTHY_AFTER = 30          # a piece that ran this long resets its restart delay
_print_lock = threading.Lock()


def log(name, message):
    with _print_lock:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] {name:>6} | {message}", flush=True)
        except OSError:
            pass  # the SSH terminal went away; keep running anyway


def can_import(python, code):
    try:
        return subprocess.run([python, "-c", code], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_pythons = {}


def python_for(piece):
    """The first Python on this Pi that has what the piece needs (smbus for lids, picamera2 for camera)."""
    if piece not in _pythons:
        candidates = [str(HERE / "servo-env" / "bin" / "python"), "/usr/bin/python3", sys.executable]
        candidates = [p for i, p in enumerate(candidates) if Path(p).exists() and p not in candidates[:i]]
        if piece == "lids":
            found = [p for p in candidates if can_import(p, "try:\n import smbus\nexcept ImportError:\n import smbus2")]
        else:  # pi_camera.py uses picamera2, or OpenCV for a USB webcam
            found = ([p for p in candidates if can_import(p, "import picamera2")] or
                     [p for p in candidates if can_import(p, "import cv2")] or candidates[1:2] or candidates)
        _pythons[piece] = found[0] if found else None
    return _pythons[piece]


NO_SMBUS = ("No Python on this Pi has smbus/smbus2, so the lids can't run. Fix with ONE of:\n"
            "    ~/servo-env/bin/pip install smbus2\n"
            "    sudo apt install python3-smbus\n"
            "  then run start_lid_pi.py again.")


def find_script(name):
    if not (HERE / name).is_file():
        raise SystemExit(f"Cannot find {name} next to {Path(__file__).name} ({HERE}).")
    return str(HERE / name)


def pi_ip():
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout.split()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "<this-pi-ip>"


def close_lids():
    """Drive both lids to their calibrated closed position, whatever state lid_server.py left them in."""
    if not python_for("lids"):
        return
    code = ("import lid; c = lid.load_calibration(); lid.setup()\n"
            "for name, ch in lid.CANS.items():\n"
            "    lid.set_pulse(ch, c[ch]['closed_us'], c); print(name + ' lid closed')")
    try:
        result = subprocess.run([python_for("lids"), "-c", code], cwd=HERE, capture_output=True,
                                text=True, timeout=10)
        output = (result.stdout + result.stderr).strip()
        log("lids", output.splitlines()[-1] if result.returncode else output.replace("\n", ", "))
    except (OSError, subprocess.SubprocessError) as exc:
        log("lids", f"Could not close the lids: {exc}")


class Piece:
    """One long-running program, restarted with a growing delay whenever it exits."""
    def __init__(self, name, cmd):
        self.name, self.cmd = name, cmd
        self.process = None
        self.started = 0.0
        self.backoff = 1
        self.restart_at = 0.0

    def start(self):
        try:
            # Own session, so Ctrl+C reaches only start_lid_pi.py and it can stop pieces in order.
            self.process = subprocess.Popen(self.cmd, cwd=HERE, env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            bufsize=1, start_new_session=True)
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
        if time.monotonic() - self.started > HEALTHY_AFTER:
            self.backoff = 1
        self.schedule_restart()

    def stop(self):
        """Ctrl+C first so the script cleans up (lid_server.py closes the lids), then force it."""
        for sig, seconds in ((signal.SIGINT, 5), (signal.SIGTERM, 2), (signal.SIGKILL, 1)):
            if not self.process or self.process.poll() is not None:
                return
            try:
                os.killpg(self.process.pid, sig)
                self.process.wait(seconds)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass


# ---- stop ------------------------------------------------------------------

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


def our_processes():
    """Return {pid: command} for every lid/camera script running, except this process."""
    me = {os.getpid(), os.getppid()}
    found = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in me:
            continue
        try:
            names = [Path(arg).name for arg in (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
                     if arg]
        except OSError:
            continue
        if names and names[0].startswith("python") and any(name in OUR_SCRIPTS for name in names[1:3]):
            found[int(entry.name)] = " ".join(names)
    return found


def stop_everything():
    log("pi", "Stopping lid and camera programs...")
    # The running start_lid_pi.py first: it stops its own pieces in order and closes the lids.
    try:
        supervisor = int(PID_FILE.read_text())
        if supervisor != os.getpid() and alive(supervisor):
            log("pi", f"start_lid_pi.py (pid {supervisor})")
            os.kill(supervisor, signal.SIGTERM)
            if wait_gone([supervisor], 15):
                os.kill(supervisor, signal.SIGKILL)
    except (OSError, ValueError):
        pass
    PID_FILE.unlink(missing_ok=True)

    # Then anything still running, including scripts started by hand in other terminals.
    leftovers = our_processes()
    for pid, cmd in leftovers.items():
        log("pi", f"{cmd} (pid {pid})")
    for sig, seconds in ((signal.SIGINT, 4), (signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        for pid in leftovers:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        remaining = wait_gone(list(leftovers), seconds)
        leftovers = {pid: leftovers[pid] for pid in remaining}
        if not leftovers:
            break
    for pid, cmd in leftovers.items():
        log("pi", f"Could not stop {cmd} (pid {pid}); try: sudo kill -9 {pid}")

    close_lids()
    for kind, port, what in ((socket.SOCK_DGRAM, 5006, "lids"), (socket.SOCK_STREAM, 8080, "camera")):
        sock = socket.socket(socket.AF_INET, kind)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            log("pi", f"Port {port} ({what}) is still in use; check: sudo ss -lunpt | grep {port}")
        finally:
            sock.close()
    log("pi", "Stopped.")


# ---- start -----------------------------------------------------------------

def run(args):
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text())
            if "start_lid_pi.py" not in Path(f"/proc/{old}/cmdline").read_bytes().decode(errors="replace"):
                raise ValueError("pid reused by another program")
            raise SystemExit(f"start_lid_pi.py is already running (pid {old}). Stop it first: python3 end_lid_pi.py")
        except (ValueError, OSError):
            pass  # stale file from a crash
    # Copies of the scripts started by hand would hold the ports and the camera.
    if our_processes():
        log("pi", "Lid/camera scripts are already running; stopping them first.")
        stop_everything()

    pieces = []
    if not args.no_lid:
        if python_for("lids"):
            log("lids", f"using {python_for('lids')}")
            pieces.append(Piece("lids", [python_for("lids"), find_script("lid_server.py")]))
        else:
            log("lids", NO_SMBUS)
            args.no_lid = True
    if not args.no_camera:
        log("camera", f"using {python_for('camera')}")
        camera = [python_for("camera"), find_script("pi_camera.py")]
        if args.usb_camera is not None:
            camera += ["--usb", str(args.usb_camera)]
        pieces.append(Piece("camera", camera))
    if not pieces:
        raise SystemExit("Nothing to run with both --no-lid and --no-camera.")

    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    signal.signal(signal.SIGHUP, signal.SIG_IGN)  # keep running if SSH drops
    PID_FILE.write_text(str(os.getpid()))

    ip = pi_ip()
    laptop = "web_server.py --host 127.0.0.1 --http"
    if not args.no_lid:
        laptop += f" --enable-lid --lid-host {ip}"
    if not args.no_camera:
        laptop += f" --camera http://{ip}:8080/stream.mjpg"
    log("pi", f"Lid Pi starting on {ip}")
    log("pi", f"On the laptop: {laptop}")
    log("pi", "Press Ctrl+C to stop everything (or run: python3 end_lid_pi.py).")
    try:
        for piece in pieces:
            piece.start()
        while not stopping.wait(0.5):
            for piece in pieces:
                piece.check()
    finally:
        log("pi", "Stopping...")
        for piece in reversed(pieces):
            piece.stop()
        if not args.no_lid:
            close_lids()
        PID_FILE.unlink(missing_ok=True)
        log("pi", "Stopped.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-lid", action="store_true", help="don't start lid_server.py")
    parser.add_argument("--no-camera", action="store_true", help="don't start pi_camera.py")
    parser.add_argument("--usb-camera", type=int, metavar="INDEX", help="stream this USB webcam, not the Pi camera")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
