"""Shared recognition, stable item readings, and camera capture for the dashboard."""
import sys
import threading
import time
import uuid
import cv2
from classifier import DROP_OFF, TrashClassifier, center_box, display_name

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
                        if isinstance(self.camera, str):
                            backend = cv2.CAP_FFMPEG  # network stream, e.g. pi_camera.py
                        else:
                            backend = cv2.CAP_AVFOUNDATION if sys.platform == 'darwin' else cv2.CAP_ANY
                        cap = cv2.VideoCapture(self.camera, backend)
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        cap.set(cv2.CAP_PROP_FPS, 30)
                    started = time.monotonic()
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        raise ValueError(f"Cannot read camera stream {self.camera}. Check that pi_camera.py is running."
                                         if isinstance(self.camera, str) else
                                         "Cannot read connected camera. Check camera permissions and close other camera apps.")
                    x, y, box_width, box_height = center_box(frame)
                    height, width = frame.shape[:2]
                    scale = min(1.0, 640 / max(height, width))
                    preview = cv2.resize(frame, (round(width * scale), round(height * scale)))
                    cv2.rectangle(preview, (round(x * scale), round(y * scale)),
                                  (round((x + box_width) * scale) - 1, round((y + box_height) * scale) - 1),
                                  (80, 255, 120), 2)
                    frame = frame[y:y + box_height, x:x + box_width].copy()
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


class ItemLock:
    """Picks the best label over a few live readings, then holds it until the item leaves."""
    READINGS = 3      # readings to compare before locking a label
    CLEAR_AFTER = 2   # empty readings in a row that mean the item was removed
    SWITCH_AFTER = 4  # readings of a different item in a row that replace the lock
    IDLE_RESET = 3.0  # seconds without readings (camera stopped) that start over

    def __init__(self):
        self.reset()
        self.last = 0.0

    # Fast GPU readings would meet the counts above in a fraction of a second, so a hand
    # passing in front of the item would start a second scan. These times must also pass.
    LOCK_SECONDS = 0.5    # readings must span this long before locking
    CLEAR_SECONDS = 1.0   # the item must be gone this long before the lock clears
    SWITCH_SECONDS = 1.0  # a different item must be seen this long before replacing the lock

    def reset(self):
        self.samples, self.locked, self.misses, self.others = [], None, 0, 0
        self.scan_id = None
        self.first = self.miss_since = self.other_since = None

    def update(self, result):
        now = time.monotonic()
        # Model time is active scanning, even when CLIP is slow on the CPU.
        if now - self.last - result.get("seconds", 0) > self.IDLE_RESET:
            self.reset()
        self.last = now
        empty = result["category"] is None
        if self.locked:
            other = not empty and result["label"] != self.locked["label"]
            self.misses = self.misses + 1 if empty else 0
            self.others = self.others + 1 if other else 0
            self.miss_since = (self.miss_since or now) if empty else None
            self.other_since = (self.other_since or now) if other else None
            if self.misses >= self.CLEAR_AFTER and now - self.miss_since >= self.CLEAR_SECONDS:
                self.reset()
                return {**result, "state": "empty"}
            if self.others < self.SWITCH_AFTER or now - self.other_since < self.SWITCH_SECONDS:
                return {**self.locked, "state": "locked", "seconds": result["seconds"], "scan_id": self.scan_id}
            self.reset()
        if empty:
            self.samples, self.first = [], None
            return {**result, "state": "empty"}
        self.samples.append(result)
        self.first = self.first or now
        if len(self.samples) < self.READINGS or now - self.first < self.LOCK_SECONDS:
            return {**result, "state": "checking", "checks": min(len(self.samples), self.READINGS), "of": self.READINGS}
        totals = {}
        for sample in self.samples:
            totals[sample["label"]] = totals.get(sample["label"], 0) + sample["score"]
        best = max(totals, key=totals.get)
        self.locked = max((sample for sample in self.samples if sample["label"] == best), key=lambda sample: sample["score"])
        self.scan_id = str(uuid.uuid4())
        self.samples = []
        return {**self.locked, "state": "locked", "scan_id": self.scan_id}


class Service:
    def __init__(self, camera=0, lid=None):
        self.camera = camera
        self.lid = lid
        self.item = ItemLock()
        self.model = None
        self.error = None
        self.lock = threading.Lock()
        self.capture = CameraStream(camera)

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
        return {"label": display_name(label), "score": score, "category": self.model.category,
                "drop_off": bool(self.model.category and alternatives and alternatives[0][0] in DROP_OFF),
                "alternatives": [{"label": display_name(name), "score": value}
                                 for name, value in alternatives],
                "seconds": round(time.monotonic() - started, 2)}

    def track(self, result):
        """Lock live readings onto one item; keep its can's lid open while it stays in view."""
        result = self.item.update(result)
        # Drop-off items (batteries, electronics) do not belong in the curbside recycling can.
        if self.lid and result["state"] == "locked" and result["category"] in ("Trash", "Recyclable") \
                and not result["drop_off"]:
            self.lid.open(result["category"])
        return result
