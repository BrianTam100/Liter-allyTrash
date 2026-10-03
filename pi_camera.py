"""Run on the Pi: streams its camera over Wi-Fi so web_server.py on another computer can use it.

On the computer running the model:  web_server.py --camera http://<pi-ip>:8080/stream.mjpg
"""
import argparse
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

WIDTH, HEIGHT, FPS = 640, 480, 20


class Camera:
    """Captures from a Pi camera module (Picamera2) or a USB webcam (OpenCV)."""
    def __init__(self, usb_index=None):
        self.condition = threading.Condition()
        self.jpeg = None
        self.sequence = 0
        if usb_index is None:
            try:
                from picamera2 import Picamera2
                self.picam = Picamera2()
                # "RGB888" arrays are in BGR order, the same as OpenCV.
                self.picam.configure(self.picam.create_video_configuration(
                    main={"size": (WIDTH, HEIGHT), "format": "RGB888"}))
                self.picam.start()
                self.read = self.picam.capture_array
                print("Using the Pi camera module.", flush=True)
            except Exception as exc:
                print(f"No Pi camera module ({exc}); trying a USB webcam.", flush=True)
                usb_index = 0
        if usb_index is not None:
            import cv2
            self.cap = cv2.VideoCapture(usb_index)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
            if not self.cap.isOpened():
                raise SystemExit(f"Cannot open USB camera {usb_index}.")
            self.read = lambda: self.cap.read()[1]
            print(f"Using USB camera {usb_index}.", flush=True)
        threading.Thread(target=self.run, daemon=True).start()

    @staticmethod
    def to_bgr(frame):
        """Convert the camera's frame to 3-channel BGR."""
        if frame.ndim == 3 and frame.shape[2] == 4:  # BGRX
            return frame[:, :, :3]
        if frame.ndim == 3 and frame.shape[2] == 2:  # YUYV, from USB webcams through libcamera
            import numpy as np
            y = frame[:, :, 0].astype(np.float32)
            uv = frame[:, :, 1].astype(np.float32) - 128
            u = np.repeat(uv[:, 0::2], 2, axis=1)
            v = np.repeat(uv[:, 1::2], 2, axis=1)
            bgr = np.dstack((y + 1.772 * u, y - 0.344136 * u - 0.714136 * v, y + 1.402 * v))
            return np.clip(bgr, 0, 255).astype(np.uint8)
        return frame

    @staticmethod
    def encode(frame):
        frame = Camera.to_bgr(frame)
        try:
            import cv2
            return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
        except ImportError:
            from PIL import Image
            buffer = io.BytesIO()
            Image.fromarray(frame[:, :, ::-1]).save(buffer, "JPEG", quality=80)
            return buffer.getvalue()

    def run(self):
        last_error = None
        while True:
            started = time.monotonic()
            try:
                frame = self.read()
                if frame is not None:
                    jpeg = self.encode(frame)
                    with self.condition:
                        self.jpeg, self.sequence = jpeg, self.sequence + 1
                        self.condition.notify_all()
                last_error = None
            except Exception as exc:
                # Keep streaming after a bad frame; report each new problem once.
                if str(exc) != last_error:
                    print(f"Camera frame failed: {exc}", flush=True)
                    last_error = str(exc)
                time.sleep(0.5)
            time.sleep(max(0, 1 / FPS - (time.monotonic() - started)))

    def next_frame(self, after):
        with self.condition:
            if not self.condition.wait_for(lambda: self.sequence > after, timeout=5):
                raise OSError("Camera stopped sending frames.")
            return self.sequence, self.jpeg


def make_handler(camera):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/stream.mjpg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sequence = 0
            try:
                while True:
                    sequence, jpeg = camera.next_frame(sequence)
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except OSError:
                pass

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--usb", type=int, metavar="INDEX", help="use this USB webcam instead of the Pi camera module")
    args = parser.parse_args()
    camera = Camera(args.usb)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(camera))
    server.daemon_threads = True
    print(f"Streaming camera at http://<this-pi-ip>:{args.port}/stream.mjpg", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
