"""Authenticated classifier routes shared by both dashboard entry points."""
from __future__ import annotations

import io
import os
import threading
import time
import uuid
from functools import wraps

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Response, g, jsonify, request, session

from classifier_service import Service

MAX_UPLOAD = 8 * 1024 * 1024


class Detector:
    def __init__(self, service, rover):
        self.service, self.rover = service, rover
        self.lock = threading.RLock()
        self.owner = None
        self.source = None
        self.heartbeat_at = 0.0
        self.loading = False
        self.generation = 0
        self.pending = {}
        self.closed = threading.Event()
        self.monitor = threading.Thread(target=self.watchdog, daemon=True)
        self.monitor.start()

    def load(self):
        with self.lock:
            if self.loading or self.service.model is not None:
                return
            self.loading = True
            self.service.error = None

        def worker():
            try:
                self.service.load()
            finally:
                self.loading = False
        threading.Thread(target=worker, daemon=True).start()

    def status(self, owner=None):
        with self.lock:
            return {"ready": self.service.model is not None, "loading": self.loading,
                "error": self.service.error, "owned": bool(owner and owner == self.owner),
                "busy": bool(self.owner and owner != self.owner), "source": self.source,
                "generation": self.generation,
                "lid_enabled": self.service.lid is not None}

    def start(self, owner, source):
        if not isinstance(source, str) or source not in {"browser", "server"}:
            raise ValueError("Choose a device camera or connected camera.")
        with self.lock:
            if self.owner and self.owner != owner:
                raise ValueError("Another person is using the live scanner. Try a photo or wait for them to finish.")
            if self.service.model is None:
                raise ValueError(self.service.error or "The scanner is still preparing. Try again when it is ready.")
            if source == "server" and self.service.camera == 0 and self.rover.status(owner)["mode"] == "gesture":
                raise ValueError("Turn off hand tracking before using the same connected camera for scanning.")
            self.stop(owner)
            self.generation += 1
            self.owner, self.source = owner, source
            self.heartbeat_at = time.monotonic()
            self.service.item.reset()
            if source == "server":
                self.service.capture.subscribe()

    def require_owner(self, owner):
        if not owner or owner != self.owner:
            raise ValueError("Start a live scan before requesting camera readings.")

    def heartbeat(self, owner):
        with self.lock:
            self.require_owner(owner)
            self.heartbeat_at = time.monotonic()

    def stop(self, owner):
        with self.lock:
            if not owner or owner != self.owner:
                return
            if self.source == "server":
                self.service.capture.unsubscribe()
            self.owner, self.source = None, None
            self.generation += 1
            self.service.item.reset()
            if self.service.lid:
                self.service.lid.close()

    def prepare_gesture(self, owner):
        with self.lock:
            if self.service.camera == 0 and self.owner and self.source == "server":
                if self.owner != owner:
                    raise ValueError("The connected camera is in use by another person's scanner.")
                self.stop(owner)

    def remember(self, owner, result):
        if result.get("category") in {"Trash", "Recyclable"} and not result.get("drop_off") and result.get("state") != "checking":
            scan_id = result.get("scan_id") or str(uuid.uuid4())
            result = {**result, "scan_id": scan_id}
            self.pending[owner] = (time.monotonic(), result)
        return result

    def recognized(self, owner, scan_id):
        with self.lock:
            stored = self.pending.get(owner)
            if not stored or time.monotonic() - stored[0] > 300 or stored[1]["scan_id"] != scan_id:
                raise ValueError("This scan has expired or belongs to another person. Scan the item again.")
            return dict(stored[1])

    def watchdog(self):
        while not self.closed.wait(0.25):
            with self.lock:
                if self.owner and time.monotonic() - self.heartbeat_at > 3:
                    self.stop(self.owner)
                now = time.monotonic()
                for owner, (created, _) in list(self.pending.items()):
                    if now - created > 300:
                        self.pending.pop(owner, None)

    def close(self):
        self.closed.set()
        self.stop(self.owner)
        self.service.capture.close()


def mount_classifier(app, service=None, autoload=True):
    if service is None:
        camera = os.getenv("CLASSIFIER_CAMERA", "0")
        lid = None
        if os.getenv("CLASSIFIER_LID_ENABLED", "false").lower() == "true":
            from lid import RemoteLid
            lid = RemoteLid(os.getenv("LID_HOST") or None, int(os.getenv("LID_PORT", "5006")))
        service = Service(int(camera) if camera.isdigit() else camera, lid)
    detector = Detector(service, app.extensions["rover"])
    app.extensions["classifier"] = detector

    def authenticated(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return jsonify(error="Sign in to scan items and record your recycling."), 401
            return view(*args, **kwargs)
        return wrapped

    @app.get("/api/classifier/status")
    def classifier_status():
        return jsonify(detector.status(session.get("pilot_token")))

    @app.post("/api/classifier/load")
    @authenticated
    def classifier_load():
        detector.load()
        return jsonify(detector.status(session.get("pilot_token")))

    @app.post("/api/classifier/<action>")
    @authenticated
    def classifier_action(action):
        owner = session["pilot_token"]
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        try:
            if action == "start":
                detector.start(owner, payload.get("source", "browser"))
            elif action == "stop":
                if payload.get("generation", detector.generation) == detector.generation:
                    detector.stop(owner)
            elif action == "heartbeat":
                if payload.get("generation", detector.generation) != detector.generation:
                    raise ValueError("This camera session ended. Start the scan again.")
                detector.heartbeat(owner)
            elif action == "confirm":
                count = payload.get("count", 1)
                if type(count) is not int or not 1 <= count <= 1000:
                    raise ValueError("Enter 1–1,000 items.")
                result = detector.recognized(owner, payload.get("scan_id"))
                category = "recycling" if result["category"] == "Recyclable" else "trash"
                db = app.extensions["database"]
                added = db.add_collection(g.user["id"], category, count, result["scan_id"], result["label"])
                return jsonify(saved=added, stats=db.stats(g.user["id"])), 201 if added else 200
            else:
                return jsonify(error="Unknown scanner action."), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify({**detector.status(owner), "url": f"/api/classifier/stream?generation={detector.generation}"})

    @app.post("/api/classifier/predict")
    @app.post("/api/classifier/camera")
    @authenticated
    def classifier_predict():
        owner = session["pilot_token"]
        server_camera = request.path.endswith("/camera")
        live = server_camera or request.headers.get("X-Trash-Live") == "1"
        generation = request.headers.get("X-Trash-Session")
        if service.model is None:
            return jsonify(error=service.error or "Scanner is still preparing."), 503
        if not service.lock.acquire(blocking=False):
            return jsonify(error="The scanner is busy. Try again shortly."), 429
        try:
            if live:
                with detector.lock:
                    detector.require_owner(owner)
                    if generation != str(detector.generation):
                        raise ValueError("This camera session ended. Start the scan again.")
                    if server_camera != (detector.source == "server"):
                        raise ValueError("The selected camera source changed. Start the scan again.")
            if server_camera:
                _, frame, _ = service.capture.latest()
            else:
                size = request.content_length or 0
                if not 0 < size <= MAX_UPLOAD:
                    raise ValueError("Choose an image smaller than 8 MB.")
                try:
                    with Image.open(io.BytesIO(request.get_data())) as picture:
                        if picture.width * picture.height > 20_000_000:
                            raise ValueError("Image is too large. Maximum: 20 megapixels.")
                        picture = ImageOps.exif_transpose(picture).convert("RGB")
                        picture.thumbnail((1280, 1280))
                        frame = cv2.cvtColor(np.asarray(picture), cv2.COLOR_RGB2BGR)
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                    raise ValueError("Could not read that image. Choose another photo.") from exc
            result = service.predict(frame)
            with detector.lock:
                if live:
                    detector.require_owner(owner)  # A late inference must not reopen a stopped lid.
                    if generation != str(detector.generation):
                        raise ValueError("This camera session ended. Start the scan again.")
                    result = service.track(result)
                else:
                    result = {**result, "state": "photo"}
                result = detector.remember(owner, result)
            return jsonify(result)
        except (ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Classifier prediction failed")
            return jsonify(error="Could not recognize that image. Try another photo or restart the scanner."), 500
        finally:
            service.lock.release()

    @app.get("/api/classifier/stream")
    @authenticated
    def classifier_stream():
        owner = session["pilot_token"]
        generation = request.args.get("generation")
        with detector.lock:
            if detector.owner != owner or detector.source != "server" or generation != str(detector.generation):
                return jsonify(error="Start your connected camera before opening the preview."), 403

        def frames():
            sequence = None
            while not detector.closed.is_set():
                with detector.lock:
                    if detector.owner != owner or detector.source != "server" or generation != str(detector.generation):
                        return
                try:
                    sequence, _, jpeg = service.capture.latest(after=sequence)
                except ValueError:
                    return
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    if autoload:
        detector.load()
    return detector
