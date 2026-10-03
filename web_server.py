"""Local browser interface for the trash classifier (no extra dependencies)."""
import argparse
import io
import json
import secrets
import ssl
import sys
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from classifier import TrashClassifier, center_box

ROOT = Path(__file__).resolve().parent
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


class Service:
    def __init__(self, camera=0):
        self.camera = camera
        self.model = None
        self.error = None
        self.lock = threading.Lock()
        self.capture = CameraStream(camera)
        self.stream_token = secrets.token_urlsafe(32)

    def load(self):
        try:
            self.model = TrashClassifier()
        except Exception as exc:
            self.error = str(exc)

    def predict(self, frame):
        started = time.monotonic()
        label, score = self.model.predict(frame)
        return {"label": label, "score": score,
                "alternatives": [{"label": name, "score": value}
                                 for name, value in self.model.alternatives],
                "seconds": round(time.monotonic() - started, 2)}


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
                self.respond(200, result)
            except (ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception as exc:
                self.respond(500, {"error": "Prediction failed: " + str(exc)})
            finally:
                service.lock.release()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--cert", help="TLS certificate (PEM) to serve HTTPS")
    parser.add_argument("--key", help="TLS private key (PEM) for --cert")
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error("--cert and --key must be used together")
    service = Service(args.camera)
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
    print(f"Trash detector: {scheme}://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.capture.close()
        server.server_close()


if __name__ == "__main__":
    main()
