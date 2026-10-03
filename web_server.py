"""Local browser interface for the trash classifier (no extra dependencies)."""
import argparse
import io
import json
import secrets
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from classifier import DROP_OFF, StablePrediction, TrashClassifier, center_box

ROOT = Path(__file__).resolve().parent
CA_CERT = ROOT / "ca.pem"
MAX_UPLOAD = 8 * 1024 * 1024


class CameraStream:
    """One capture worker; preview and inference consume the latest frame."""
    def __init__(self, camera):
        self.camera = camera
        self.condition = threading.Condition()
        self.clients = 0
        self.frame = self.jpeg = None
        self.sequence = 0
        self.error = None
        self.closed = False
        self.thread = None

    def subscribe(self):
        with self.condition:
            self.clients += 1
            self.error = None
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def unsubscribe(self):
        with self.condition:
            self.clients -= 1
            if not self.clients:
                self.frame = self.jpeg = None
            self.condition.notify_all()

    def latest(self, after=None):
        with self.condition:
            available = self.condition.wait_for(
                lambda: self.closed or self.error or
                (self.frame is not None and (after is None or self.sequence > after)),
                timeout=10)
            if self.error:
                raise ValueError(self.error)
            if self.closed or not available:
                raise ValueError("Camera stream unavailable. Stop and restart the camera.")
            return self.sequence, self.frame.copy(), self.jpeg

    def run(self):
        cap = None
        try:
            while True:
                with self.condition:
                    if not self.clients or self.error:
                        if cap is not None:
                            cap.release()
                            cap = None
                        self.condition.wait_for(lambda: self.closed or (self.clients and not self.error))
                    if self.closed:
                        return
                try:
                    if cap is None:
                        backend = cv2.CAP_AVFOUNDATION if sys.platform == 'darwin' else cv2.CAP_ANY
                        cap = cv2.VideoCapture(self.camera, backend)
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        cap.set(cv2.CAP_PROP_FPS, 30)
                    started = time.monotonic()
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        raise ValueError("Cannot read connected camera. Check camera permissions and close other camera apps.")
                    x, y, size = center_box(frame)
                    height, width = frame.shape[:2]
                    scale = min(1.0, 640 / max(height, width))
                    preview = cv2.resize(frame, (round(width * scale), round(height * scale)))
                    cv2.rectangle(preview, (round(x * scale), round(y * scale)),
                                  (round((x + size) * scale), round((y + size) * scale)),
                                  (80, 255, 120), 2)
                    frame = frame[y:y + size, x:x + size].copy()
                    ok, encoded = cv2.imencode('.jpg', cv2.flip(preview, 1), [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if not ok:
                        raise ValueError("Camera frame encoding failed.")
                    with self.condition:
                        if self.clients:
                            self.frame, self.jpeg = frame, encoded.tobytes()
                            self.sequence += 1
                            self.condition.notify_all()
                    time.sleep(max(0, 1 / 30 - (time.monotonic() - started)))
                except Exception as exc:
                    with self.condition:
                        self.error = str(exc)
                        self.condition.notify_all()
        finally:
            if cap is not None:
                cap.release()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=3)


class Lid:
    """Lid servo on a PCA9685 I2C board; opens on trash, then closes after a delay."""
    ADDR, MODE1, PRESCALE, LED0 = 0x40, 0x00, 0xFE, 0x06

    def __init__(self, channel=None, open_us=1944, closed_us=1167, hold_seconds=5.0, i2c_bus=1):
        # channel=None drives all 16 outputs, like the original test script.
        self.channels = range(16) if channel is None else [channel]
        self.open_us, self.closed_us, self.hold_seconds = open_us, closed_us, hold_seconds
        self.lock = threading.Lock()
        self.timer = None
        self.is_open = False
        try:
            try:
                from smbus import SMBus
            except ImportError:
                from smbus2 import SMBus
            self.bus = SMBus(i2c_bus)
            self.bus.write_byte_data(self.ADDR, self.MODE1, 0x10)    # sleep to set frequency
            self.bus.write_byte_data(self.ADDR, self.PRESCALE, 121)  # ~50 Hz servo pulses
            self.bus.write_byte_data(self.ADDR, self.MODE1, 0x20)    # wake, auto-increment
            time.sleep(0.01)
            self.move(closed_us)
            print(f"Lid servo ready on PCA9685 0x{self.ADDR:02x}.", flush=True)
        except Exception as exc:
            self.bus = None
            print(f"Lid servo disabled ({exc}).", file=sys.stderr, flush=True)

    def move(self, pulse_us):
        count = int(pulse_us * 4096 / 20000)
        for channel in self.channels:
            reg = self.LED0 + 4 * channel
            self.bus.write_byte_data(self.ADDR, reg, 0)
            self.bus.write_byte_data(self.ADDR, reg + 1, 0)
            self.bus.write_byte_data(self.ADDR, reg + 2, count & 0xFF)
            self.bus.write_byte_data(self.ADDR, reg + 3, (count >> 8) & 0x0F)

    def open(self):
        """Open the lid, or keep it open, for another hold_seconds."""
        if self.bus is None:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            if not self.is_open:
                self.is_open = True
                self.move(self.open_us)
                print("Trash detected: opening lid.", flush=True)
            self.timer = threading.Timer(self.hold_seconds, self.close)
            self.timer.daemon = True
            self.timer.start()

    def close(self):
        if self.bus is None:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.timer = None
            if self.is_open:
                self.is_open = False
                self.move(self.closed_us)
                print("Closing lid.", flush=True)


class Service:
    def __init__(self, camera=0, lid=None):
        self.camera = camera
        self.lid = lid
        self.stable = StablePrediction()
        self.model = None
        self.error = None
        self.lock = threading.Lock()
        self.capture = CameraStream(camera)
        self.stream_token = secrets.token_urlsafe(32)

    def load(self):
        try:
            self.model = TrashClassifier()
            print("Model ready.", flush=True)
        except Exception as exc:
            self.error = str(exc)
            print(f"Model failed to load: {exc}", file=sys.stderr, flush=True)

    def predict(self, frame):
        started = time.monotonic()
        label, score = self.model.predict(frame)
        alternatives = self.model.alternatives
        return {"label": label, "score": score, "category": self.model.category,
                "drop_off": bool(self.model.category and alternatives and alternatives[0][0] in DROP_OFF),
                "alternatives": [{"label": name, "score": value}
                                 for name, value in alternatives],
                "seconds": round(time.monotonic() - started, 2)}

    def update_lid(self, result):
        """Open the lid once two successive live readings agree on a trash item."""
        label = self.stable.update(result["label"])
        if self.lid and result["category"] == "Trash" and not label.startswith(("Hold", "No trash", "Image")):
            self.lid.open()


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def respond(self, status, value, content_type="application/json"):
            body = json.dumps(value).encode() if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/api/stream':
                token = parse_qs(parsed.query).get('token', [''])[0]
                if not secrets.compare_digest(token, service.stream_token):
                    self.respond(403, {'error': 'Start the camera through the interface.'})
                    return
                service.capture.subscribe()
                try:
                    sequence, _, jpeg = service.capture.latest()
                    self.send_response(200)
                    self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while True:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                         str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                        self.wfile.flush()
                        sequence, _, jpeg = service.capture.latest(after=sequence)
                except (OSError, ValueError):
                    pass
                finally:
                    service.capture.unsubscribe()
                return
            if self.path == "/api/status":
                self.respond(200, {"ready": service.model is not None, "error": service.error})
            elif self.path == "/ca.crt" and CA_CERT.exists():
                self.respond(200, CA_CERT.read_bytes(), "application/x-x509-ca-cert")
            elif self.path in ("/", "/app.js", "/style.css"):
                name, mime = {"/": ("index.html", "text/html; charset=utf-8"),
                              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                              "/style.css": ("style.css", "text/css; charset=utf-8")}[self.path]
                self.respond(200, (ROOT / "web" / name).read_bytes(), mime)
            else:
                self.respond(404, {"error": "Not found"})

        def do_POST(self):
            # Custom header prevents cross-site forms from driving the local camera.
            if self.headers.get("X-Trash-UI") != "1":
                self.respond(403, {"error": "Use the trash detector interface."})
                return
            if self.path == '/api/camera/start':
                self.respond(200, {'url': '/api/stream?token=' + service.stream_token})
                return
            if self.path not in ("/api/predict", "/api/camera"):
                self.respond(404, {"error": "Not found"})
                return
            if service.model is None:
                self.respond(503, {"error": service.error or "Model is still loading."})
                return
            if not service.lock.acquire(blocking=False):
                self.respond(429, {"error": "Detector is busy. Try again shortly."})
                return
            try:
                if self.path == "/api/camera":
                    _, frame, _ = service.capture.latest()
                else:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_UPLOAD:
                        raise ValueError("Choose an image smaller than 8 MB.")
                    with Image.open(io.BytesIO(self.rfile.read(size))) as picture:
                        if picture.width * picture.height > 20_000_000:
                            raise ValueError("Image is too large. Maximum: 20 megapixels.")
                        from PIL import ImageOps
                        picture = ImageOps.exif_transpose(picture).convert("RGB")
                        picture.thumbnail((1280, 1280))
                        frame = cv2.cvtColor(np.asarray(picture), cv2.COLOR_RGB2BGR)
                result = service.predict(frame)
                # Only live camera readings move the lid; uploaded photos do not.
                if self.path == "/api/camera" or self.headers.get("X-Trash-Live") == "1":
                    service.update_lid(result)
                self.respond(200, result)
            except (ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception as exc:
                self.respond(500, {"error": "Prediction failed: " + str(exc)})
            finally:
                service.lock.release()

    return Handler


def lan_ip():
    """Return this machine's Wi-Fi/LAN address, or None if offline."""
    # Ask the OS for the Wi-Fi address first; a VPN can hijack the default route.
    for cmd in (["ipconfig", "getifaddr", "en0"], ["hostname", "-I"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.split()
        except (OSError, subprocess.SubprocessError):
            continue
        if out:
            return out[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            # No packets are sent; this only picks the outbound interface.
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


# The local CA may only sign certificates for this machine and private networks,
# so trusting it cannot be abused to impersonate real websites.
CA_CONSTRAINTS = ",".join(
    f"permitted;{name}" for name in ("DNS:localhost", "IP:127.0.0.0/255.0.0.0", "IP:10.0.0.0/255.0.0.0",
                                     "IP:172.16.0.0/255.240.0.0", "IP:192.168.0.0/255.255.0.0"))


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def ensure_ca(ca, ca_key):
    """Create the local certificate authority that devices trust once."""
    if ca.exists() and ca_key.exists():
        return
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
            "-keyout", ca_key, "-out", ca, "-subj", "/O=Trash Lens/CN=Trash Lens Local CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", f"nameConstraints=critical,{CA_CONSTRAINTS}")
    ca_key.chmod(0o600)
    print(f"Created a local certificate authority: {ca}", flush=True)


def ensure_cert(ip, cert, key, ca, ca_key):
    """Sign a certificate for localhost and ip with the local CA unless a valid one exists."""
    if cert.exists() and key.exists():
        verified = subprocess.run(["openssl", "verify", "-CAfile", ca, cert], capture_output=True).returncode == 0
        covers = not ip or subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkip", ip],
                                          capture_output=True).returncode == 0
        # Renew a month before expiry.
        fresh = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", str(30 * 86400)],
                               capture_output=True).returncode == 0
        if verified and covers and fresh:
            return
    names = "DNS:localhost,IP:127.0.0.1" + (f",IP:{ip}" if ip else "")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
            "-keyout", key, "-out", cert, "-CA", ca, "-CAkey", ca_key, "-subj", "/O=Trash Lens",
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
            "-addext", "extendedKeyUsage=serverAuth",
            "-addext", f"subjectAltName={names}")
    key.chmod(0o600)
    print(f"Created a certificate for {names}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="use 127.0.0.1 for this machine only")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--cert", help="TLS certificate (PEM) to serve HTTPS")
    parser.add_argument("--key", help="TLS private key (PEM) for --cert")
    parser.add_argument("--http", action="store_true", help="serve plain HTTP (other devices cannot use their own camera)")
    parser.add_argument("--lid-channel", type=int, help="PCA9685 channel of the lid servo (default: all 16)")
    parser.add_argument("--lid-open-us", type=int, default=1944, help="servo pulse (microseconds) for an open lid")
    parser.add_argument("--lid-closed-us", type=int, default=1167, help="servo pulse (microseconds) for a closed lid")
    parser.add_argument("--lid-seconds", type=float, default=5.0, help="keep the lid open this long after trash leaves view")
    parser.add_argument("--no-lid", action="store_true", help="do not drive the lid servo")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key must be used together")
    ip = lan_ip() if args.host == "0.0.0.0" else None
    if not args.http and not args.cert:
        # Browsers only allow camera access over HTTPS, so phones and laptops on
        # the Wi-Fi need it to use their own camera.
        args.cert, args.key = ROOT / "cert.pem", ROOT / "key.pem"
        try:
            ensure_ca(CA_CERT, ROOT / "ca-key.pem")
            ensure_cert(ip, args.cert, args.key, CA_CERT, ROOT / "ca-key.pem")
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"Could not create a certificate ({error}); serving HTTP.", flush=True)
            args.cert = args.key = None
    with socket.socket() as probe:
        # macOS lets 0.0.0.0 and 127.0.0.1 share a port, hiding an old server on localhost.
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            sys.exit(f"Port {args.port} is already in use; stop the other server or pass --port.")
    lid = None if args.no_lid else Lid(args.lid_channel, args.lid_open_us, args.lid_closed_us, args.lid_seconds)
    service = Service(args.camera, lid)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    server.daemon_threads = True
    scheme = "http"
    if args.cert:
        # HTTPS lets other devices on the network use their own browser camera.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    threading.Thread(target=service.load, daemon=True).start()
    print(f"Trash detector: {scheme}://localhost:{args.port}", flush=True)
    if ip:
        print(f"On your Wi-Fi:  {scheme}://{ip}:{args.port}", flush=True)
    if scheme == "https" and CA_CERT.exists():
        print(f"To skip the certificate warning, install {scheme}://{ip or 'localhost'}:{args.port}/ca.crt "
              "once on each device (see README).", flush=True)
    elif args.host not in ("127.0.0.1", "localhost"):
        print(f"On your network: {scheme}://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.capture.close()
        if lid:
            lid.close()
        server.server_close()


if __name__ == "__main__":
    main()
