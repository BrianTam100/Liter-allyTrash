"""Web control bridge using the existing Pi/Arduino command protocol.

No hardware is opened until a signed-in pilot explicitly connects.
The browser owns a short renewable lease; losing it sends STOP.
The Bluetooth serial port stays open between pilots, because opening it takes seconds.
"""
from __future__ import annotations

import ipaddress
import math
import os
import re
import socket
import threading
import time


BUSY = "Someone else is driving the rover right now. You can take over when they disconnect."


def list_serial_ports():
    """Serial ports on this laptop, flagging outgoing Bluetooth links to a paired device."""
    from serial.tools import list_ports
    ports = []
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        hwid = (port.hwid or "").upper()
        # Windows tags each paired device's outgoing port with its address; incoming ports use zeros.
        address = re.search(r"&([0-9A-F]{12})_", hwid) if "BTHENUM" in hwid else None
        paired = bool(address and address.group(1) != "0" * 12)
        kind = "paired Bluetooth" if paired else "incoming Bluetooth" if "BTHENUM" in hwid else \
            re.sub(r"\s*\(COM\d+\)$", "", port.description or "serial")
        ports.append({"device": port.device, "kind": kind, "paired": paired})
    return ports


def find_serial_port(configured, strict=False):
    """Use the chosen port if it exists, else the one outgoing Bluetooth port. Strict choices never fall back."""
    ports = list_serial_ports()
    found = ", ".join(f"{p['device']} ({p['kind']})" for p in ports) or "none"
    if configured and configured.lower() != "auto":
        for port in ports:
            if port["device"].upper() == configured.upper():
                return port["device"]
        if strict:
            raise ValueError(f"{configured} isn't available on this laptop. Ports found: {found}.")
    paired = [p["device"] for p in ports if p["paired"]]
    if len(paired) == 1:
        return paired[0]
    missing = f"{configured} was not found. " if configured and configured.lower() != "auto" else ""
    raise ValueError(f"{missing}Choose the rover's port in the Port menu. Ports found: {found}.")


class RoverBridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.port_lock = threading.Lock()
        self.serial = None
        self.serial_port = None
        self.transport = None
        self.link = "offline"
        self.owner = None
        self.mode = "manual"
        self.last_command = "x"
        self.speed = 5000
        self.error = None
        self.heartbeat_at = 0.0
        self.manual_until = 0.0
        self.last_manual_at = 0.0
        self.epoch = 0
        self.sequence = 0
        self.voice = None
        self.camera_thread = None
        self.camera_stop = threading.Event()
        self.frame = None
        self.camera_error = None
        self.closed = threading.Event()
        self.monitor = threading.Thread(target=self._watchdog, daemon=True)
        self.monitor.start()

    def status(self, owner=None):
        with self.lock:
            voice_error = getattr(self.voice, "error", None)
            return {"link": self.link, "connected": self.transport is not None,
                    "owned": bool(owner and owner == self.owner), "busy": bool(self.owner and owner != self.owner),
                    "mode": self.mode, "command": self.last_command.strip(), "error": self.error,
                    "speed": self.speed,
                    "voice_ready": bool(self.voice and self.voice.ready.is_set() and not voice_error),
                    "voice_error": voice_error, "camera_error": self.camera_error,
                    "camera_active": bool(self.camera_thread and self.camera_thread.is_alive()),
                    "port": self.serial_port if self.link == "bluetooth" else None,
                    "epoch": self.epoch, "sequence": self.sequence}

    def _require_owner(self, owner):
        if not self.transport:
            raise ValueError("Connect the rover before using controls.")
        if not owner or self.owner != owner:
            raise ValueError(BUSY)

    def _open_serial(self, choice=None, fresh=False):
        """Return the open Bluetooth port, opening it outside the bridge lock so status stays responsive."""
        if choice is not None and (not isinstance(choice, str) or len(choice) > 64):
            raise ValueError("Choose a serial port from the list.")
        with self.port_lock:
            if choice and choice.lower() != "auto":
                port = find_serial_port(choice, strict=True)
            else:
                port = find_serial_port(os.getenv("ROVER_SERIAL_PORT", "auto"))
            if fresh or port != self.serial_port:
                self._close_serial()
            if self.serial is None:
                import serial
                try:
                    self.serial = serial.Serial(port, int(os.getenv("ROVER_BAUD", "115200")), timeout=0.2, write_timeout=0.3)
                except serial.SerialException as exc:
                    raise ValueError(f"Could not open {port}. Check the rover is on and paired, then try again. ({exc})") from exc
                self.serial_port = port
            return self.serial

    def _close_serial(self):
        self.serial_port = None
        port, self.serial = self.serial, None
        if port:
            try:
                port.close()
            except Exception:
                pass

    def _release(self):
        """Drop the link. Bluetooth stays open for the next pilot; a Wi-Fi socket is closed."""
        if self.transport is not None and self.transport is not self.serial:
            self.transport.close()
        self.transport, self.owner, self.link = None, None, "offline"

    def connect(self, owner, kind, port=None):
        if kind not in {"bluetooth", "wifi"}:
            raise ValueError("Choose Bluetooth or Wi-Fi.")
        for attempt in range(2):
            with self.lock:
                if self.owner and self.owner != owner:
                    raise ValueError(BUSY)
                if self.transport:
                    raise ValueError("Disconnect before changing the connection.")
            # A cached port can go stale while idle, so a failed first STOP reopens it once.
            transport = self._open_serial(port, fresh=attempt > 0) if kind == "bluetooth" else None
            with self.lock:
                if self.transport or (self.owner and self.owner != owner):
                    raise ValueError(BUSY)
                if kind == "wifi":
                    host = os.getenv("PI_IP", "172.20.8.62")
                    ipaddress.ip_address(host)
                    self.target = (host, int(os.getenv("PI_UDP_PORT", "5005")))
                    transport = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.transport = transport
                self.link, self.owner = kind, owner
                self.error = None
                self.mode = "manual"
                self.epoch += 1
                self.sequence = 0
                self.heartbeat_at = time.monotonic()
                try:
                    self._send("x", force=True)
                    return
                except Exception:
                    if kind == "wifi" or attempt:
                        raise
                    self.error = None

    def _send(self, command, force=False, remember=True):
        if self.transport is None:
            return
        if command != self.last_command or force or not remember:
            payload = command.encode("ascii")
            try:
                if self.link == "wifi":
                    self.transport.sendto(payload, self.target)
                else:
                    self.transport.write(payload)
                if remember:
                    self.last_command = command
            except Exception:
                self.error = "The rover connection was lost. Reconnect before driving."
                if self.transport is self.serial:
                    self._close_serial()
                self._release()
                self.last_command = "x"
                raise

    def heartbeat(self, owner):
        with self.lock:
            self._require_owner(owner)
            self.heartbeat_at = time.monotonic()

    def command(self, owner, command, epoch, sequence):
        if not isinstance(command, str) or command not in {"w", "a", "s", "d", "z", "c", "x"}:
            raise ValueError("Unknown drive command.")
        if type(epoch) is not int or type(sequence) is not int or sequence < 1:
            raise ValueError("A valid control epoch and sequence are required.")
        with self.lock:
            self._require_owner(owner)
            # Late motion packets cannot override a release, mode change, or stop.
            if epoch != self.epoch or sequence <= self.sequence:
                return
            self.sequence = sequence
            self.heartbeat_at = time.monotonic()
            self.last_manual_at = time.monotonic()
            self.manual_until = self.last_manual_at + 0.7 if command != "x" else 0.0
            self._send(command, force=command == "x")

    def set_speed(self, owner, speed):
        if type(speed) is not int or not 100 <= speed <= 12000:
            raise ValueError("Choose a throttle value from 100 to 12,000 steps per second.")
        with self.lock:
            self._require_owner(owner)
            if self.link != "bluetooth":
                raise ValueError("Throttle updates need the Bluetooth Arduino link.")
            self.heartbeat_at = time.monotonic()
            self.speed = speed
            self._send(f"v{speed}", force=True, remember=False)

    def _assisted_command(self, owner, mode, command):
        with self.lock:
            if self.owner != owner or self.mode != mode or not self.transport:
                return
            now = time.monotonic()
            if now - self.heartbeat_at > 1.5 or now - self.last_manual_at < 0.8:
                return
            try:
                self._send(command)
            except Exception:
                pass

    def stop(self, owner):
        with self.lock:
            self._require_owner(owner)
            self.mode = "manual"  # Disable assisted callbacks immediately.
            self.epoch += 1
            self.manual_until = 0.0
            self._send("x", force=True)
        self._stop_assistance()

    def _stop_assistance(self):
        voice, self.voice = self.voice, None
        if voice:
            voice.stop()
        self.camera_stop.set()
        if self.camera_thread and self.camera_thread is not threading.current_thread():
            self.camera_thread.join(timeout=2)
        self.frame = None

    def set_mode(self, owner, mode):
        if not isinstance(mode, str) or mode not in {"manual", "voice", "gesture"}:
            raise ValueError("Choose keyboard, voice, or hand gestures.")
        self.stop(owner)
        with self.lock:
            self._require_owner(owner)
            if mode == "gesture" and self.link != "bluetooth":
                raise ValueError("Hand angles need Bluetooth; the existing Wi-Fi receiver accepts WASD only.")
            self.mode = mode
            self.camera_error = None
        try:
            if mode == "voice":
                if not os.getenv("XAI_API_KEY", "").strip():
                    raise ValueError("Set XAI_API_KEY in BRH_Test/.env to enable Grok voice.")
                if __package__:
                    from .voice_control import VoiceDrive
                else:
                    from voice_control import VoiceDrive
                voice = VoiceDrive(lambda cmd: self._assisted_command(owner, "voice", cmd))
                voice.start()
                with self.lock:
                    self.voice = voice
            elif mode == "gesture":
                import cv2
                import mediapipe as mp
                if not hasattr(mp, "solutions"):
                    raise ValueError("Hand gestures need MediaPipe with the solutions.hands API. See the setup guide.")
                self.camera_stop.clear()
                self.camera_thread = threading.Thread(target=self._camera_loop, args=(owner, cv2, mp), daemon=True)
                self.camera_thread.start()
        except Exception:
            with self.lock:
                self.mode = "manual"
                self._send("x", force=True)
            raise

    def _camera_loop(self, owner, cv2, mp):
        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                raise ValueError("Could not open the laptop camera. Close other camera apps and try again.")
            with mp.solutions.hands.Hands(max_num_hands=1, min_detection_confidence=0.7) as hands:
                while not self.camera_stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        raise ValueError("The camera stopped responding.")
                    frame = cv2.flip(frame, 1)
                    result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    command = "x"
                    if result.multi_hand_landmarks:
                        landmarks = result.multi_hand_landmarks[0]
                        mp.solutions.drawing_utils.draw_landmarks(frame, landmarks, mp.solutions.hands.HAND_CONNECTIONS)
                        wrist, tip = landmarks.landmark[0], landmarks.landmark[8]
                        angle = math.degrees(math.atan2(-(tip.y - wrist.y), tip.x - wrist.x)) % 360
                        command = f"{int(round(angle / 5) * 5) % 360}\n"
                    self._assisted_command(owner, "gesture", command)
                    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        self.frame = jpg.tobytes()
                    self.camera_stop.wait(0.08)
        except Exception as exc:
            self.camera_error = str(exc)
            with self.lock:
                if self.owner == owner and self.mode == "gesture":
                    self.mode = "manual"
                    try:
                        self._send("x", force=True)
                    except Exception:
                        pass
        finally:
            cap.release()
            self.frame = None

    def disconnect(self, owner=None):
        with self.lock:
            if owner is not None and owner != self.owner:
                return
            self.mode = "manual"
            self.epoch += 1
            try:
                self._send("x", force=True)
            except Exception:
                pass
            self._release()
            self.last_command = "x"
            self.manual_until = 0.0
        self._stop_assistance()

    def _watchdog(self):
        while not self.closed.wait(0.1):
            expired_owner = None
            stop_assistance = False
            with self.lock:
                now = time.monotonic()
                if self.transport and now - self.heartbeat_at > 1.5:
                    expired_owner = self.owner
                elif self.transport and self.manual_until and now > self.manual_until:
                    self.manual_until = 0
                    try:
                        self._send("x", force=True)
                    except Exception:
                        pass
                elif self.transport and self.mode == "voice" and self.voice and self.voice.error:
                    self.mode = "manual"
                    try:
                        self._send("x", force=True)
                    except Exception:
                        pass
                if not self.transport:
                    self.mode = "manual"
                stop_assistance = self.mode == "manual" and bool(self.voice or (self.camera_thread and self.camera_thread.is_alive()))
            if expired_owner:
                self.disconnect(expired_owner)
            elif stop_assistance:
                self._stop_assistance()

    def close(self):
        self.closed.set()
        self.disconnect()
        with self.port_lock:
            self._close_serial()
