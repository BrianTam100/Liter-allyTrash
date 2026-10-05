"""Litter-ally Trash dashboard. Run on the laptop paired with the Raspberry Pi."""
from __future__ import annotations

import argparse
import atexit
import hmac
import os
import secrets
import threading
import time
import uuid
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, render_template, request, session
from jinja2 import ChoiceLoader, FileSystemLoader

if __package__:
    from .database import Database
    from .rover_bridge import RoverBridge, RoverConnectionError, list_serial_ports
else:
    from database import Database
    from rover_bridge import RoverBridge, RoverConnectionError, list_serial_ports

ROOT = Path(__file__).resolve().parent
# Accounts are not used: every visitor's can counts go to this one local pilot.
PILOT_EMAIL = "pilot@literally-trash.local"
PILOT_NAME = "Pilot"
# Dashboard bin name -> lid name used by lid.py.
BIN_LIDS = {"trash": "Trash", "recycling": "Recyclable"}
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def create_app(config=None, bridge=None, classifier_service=None):
    load_dotenv(ROOT / ".env")
    app = Flask(__name__, template_folder="website/templates", static_folder=str(PROJECT_ROOT / "web"), static_url_path="/static")
    app.jinja_loader = ChoiceLoader([FileSystemLoader(str(PROJECT_ROOT / "web")), app.jinja_loader])
    app.config.update(SECRET_KEY=os.getenv("SECRET_KEY", ""), DATABASE_URL=os.getenv("DATABASE_URL", "").strip(),
        SQLITE_PATH=str(ROOT / ".instance" / "literally-trash.db"), SESSION_COOKIE_HTTPONLY=True,
        COLLECTION_API_KEY=os.getenv("COLLECTION_API_KEY", ""),
        SPECTRUM_BRIDGE_KEY=os.getenv("SPECTRUM_BRIDGE_KEY", ""),
        SPECTRUM_PROJECT_ID=os.getenv("SPECTRUM_PROJECT_ID", ""),
        SPECTRUM_PROJECT_SECRET=os.getenv("SPECTRUM_PROJECT_SECRET", ""),
        SPECTRUM_ALLOWED_SENDERS=os.getenv("SPECTRUM_ALLOWED_SENDERS", ""),
        SPECTRUM_TELEGRAM_ALLOWED_SENDERS=os.getenv("SPECTRUM_TELEGRAM_ALLOWED_SENDERS", ""),
        SPECTRUM_PROVIDER=os.getenv("SPECTRUM_PROVIDER", "imessage"),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
        GEMINI_CHAT_MODEL=os.getenv("GEMINI_CHAT_MODEL", "gemini-3.7-flash"),
        XAI_API_KEY=os.getenv("XAI_API_KEY", ""),
        XAI_CHAT_MODEL=os.getenv("XAI_CHAT_MODEL", "grok-4.7"),
        SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        CLASSIFIER_AUTOLOAD=os.getenv("CLASSIFIER_AUTOLOAD", "true").lower() == "true",
        SEND_FILE_MAX_AGE_DEFAULT=31536000)
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        key_path = ROOT / ".instance" / "session.key"
        key_path.parent.mkdir(exist_ok=True)
        if not key_path.exists():
            try:
                with key_path.open("x", encoding="utf-8") as key_file:
                    key_file.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        app.config["SECRET_KEY"] = key_path.read_text(encoding="utf-8").strip()
    db = Database(app.config["DATABASE_URL"], app.config["SQLITE_PATH"])
    atexit.register(db.close)
    if not db.is_tiger:
        db.initialize()
    rover = bridge or RoverBridge()
    app.extensions.update(database=db, rover=rover)
    atexit.register(rover.close)
    from dashboard_classifier import mount_classifier
    detector = mount_classifier(app, classifier_service, autoload=app.config["CLASSIFIER_AUTOLOAD"] and not app.testing)
    atexit.register(detector.close)
    pilot_lock = threading.Lock()
    pilot = {}
    log_cache = {}
    log_cache_lock = threading.Lock()
    dashboard_cache = {}
    dashboard_cache_lock = threading.Lock()

    def pilot_user():
        with pilot_lock:
            if "id" not in pilot:
                account = db.user_by_email(PILOT_EMAIL)
                pilot["id"] = account["id"] if account else db.create_user(PILOT_EMAIL, PILOT_NAME, "")
                pilot["user"] = {"id": pilot["id"], "email": PILOT_EMAIL, "display_name": PILOT_NAME}
        return pilot["user"]

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.url_defaults
    def static_version(endpoint, values):
        # Assets are cached for a year; the file's timestamp in the URL fetches a new copy after edits.
        if endpoint == "static" and "filename" in values:
            asset = Path(app.static_folder) / values["filename"]
            values["v"] = int(asset.stat().st_mtime) if asset.is_file() else 0

    @app.before_request
    def prepare_request():
        if request.endpoint == "static":
            return
        if request.path.startswith("/api/integrations/spectrum/"):
            configured = app.config["SPECTRUM_BRIDGE_KEY"]
            supplied = request.headers.get("Authorization", "")
            if not configured or not hmac.compare_digest(supplied, "Bearer " + configured):
                return jsonify(error="A valid Spectrum bridge key is required."), 401
            g.user = None
            return
        if request.endpoint == "bin_event":
            configured = app.config["COLLECTION_API_KEY"]
            supplied = request.headers.get("Authorization", "")
            if not configured or not hmac.compare_digest(supplied, "Bearer " + configured):
                return jsonify(error="A valid bin API key is required."), 401
            g.user = None
            return
        # Each browser still gets its own pilot token so rover/camera leases stay per-visitor.
        session.setdefault("pilot_token", secrets.token_urlsafe(24))
        g.user = pilot_user()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not supplied or not expected or not hmac.compare_digest(supplied, expected):
                if request.path.startswith("/api/"):
                    return jsonify(error="Your session changed. Refresh the page and try again."), 403
                return render_template("error.html", message="Your session changed. Refresh the page and try again."), 403

    @app.context_processor
    def common_context():
        return {"user": getattr(g, "user", None), "storage_label": "TigerData" if db.is_tiger else "Local development"}

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        with dashboard_cache_lock:
            revision = db.log_cache_revision
            cached = dashboard_cache.get(g.user["id"])
            if cached is None or cached[0] != revision or time.monotonic() - cached[1] >= 30:
                data = dict(stats=db.stats(g.user["id"]), recent=db.recent(g.user["id"]))
                dashboard_cache[g.user["id"]] = (revision, time.monotonic(), data)
            else:
                data = cached[2]
        return render_template("index.html", **data)

    @app.get("/controls")
    def controls():
        return render_template("controls.html")

    @app.get("/log")
    def detection_log():
        period = request.args.get("period", "all")
        if period not in {"all", "week", "month"}:
            period = "all"
        # Cache data on the laptop, separately for each time filter. Render the
        # page per visitor so session/CSRF tokens never enter the shared cache.
        with log_cache_lock:
            revision = db.log_cache_revision
            cached = log_cache.get(period)
            if cached is None or cached[0] != revision or time.monotonic() - cached[1] >= 30:
                data = dict(summary=db.detection_summary(period), items=db.detection_items(period),
                    log=db.detections(period), bins=db.bin_contents())
                log_cache[period] = (revision, time.monotonic(), data)
            else:
                data = cached[2]
        return render_template("detections.html", period=period, **data,
            lid_available=detector.service.lid is not None)

    @app.get("/settings")
    def settings():
        return render_template("settings.html", demo_mode=session.get("demo_mode", False))

    @app.post("/api/settings/demo-mode")
    def demo_mode():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
            return jsonify(error="Choose whether demo mode is enabled."), 400
        rover.disconnect(session["pilot_token"])
        session["demo_mode"] = payload["enabled"]
        session.permanent = True
        return jsonify(demo_mode=session["demo_mode"])

    @app.post("/api/settings/clear-data")
    def clear_data():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or payload.get("confirm") != "DELETE":
            return jsonify(error="Type DELETE to confirm."), 400
        db.clear_all()
        return jsonify(cleared=True)

    @app.post("/api/bins/<category>/<action>")
    def bin_action(category, action):
        # open: the browser repeats this every few seconds while someone empties the bin,
        # because the Pi closes an idle lid after 5 s. done: close it and clear the contents.
        if category not in BIN_LIDS or action not in {"open", "close", "done"}:
            return jsonify(error="Unknown bin action."), 404
        lid = detector.service.lid
        if action == "open":
            if lid:
                lid.open(BIN_LIDS[category])
            return jsonify(lid=lid is not None)
        if lid:
            lid.close(BIN_LIDS[category])
        if action == "close":
            return jsonify(closed=True)
        cleared = db.empty_bin(category)
        return jsonify(cleared=cleared, bins=db.bin_contents())

    @app.get("/api/rover")
    def rover_status():
        return jsonify(**rover.status(session.get("pilot_token")), demo_mode=session.get("demo_mode", False))

    @app.get("/api/rover/ports")
    def rover_ports():
        try:
            return jsonify(ports=list_serial_ports())
        except ImportError:
            return jsonify(ports=[])

    @app.post("/api/rover/<action>")
    def rover_action(action):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        owner = session["pilot_token"]
        try:
            if action == "connect":
                kind = "demo" if session.get("demo_mode") else payload.get("transport", "bluetooth")
                if kind == "demo" and not session.get("demo_mode"):
                    raise ValueError("Enable demo mode in Settings first.")
                rover.connect(owner, kind, payload.get("port"))
            elif action == "disconnect":
                rover.disconnect(owner)
            elif action == "heartbeat":
                rover.heartbeat(owner)
            elif action == "command":
                rover.command(owner, payload.get("command", "x"), payload.get("epoch"), payload.get("sequence"))
            elif action == "speed":
                rover.set_speed(owner, payload.get("speed"))
            elif action == "stop":
                rover.stop(owner)
            elif action == "mode":
                if session.get("demo_mode") and not rover.status(owner)["connected"]:
                    rover.connect(owner, "demo")
                if payload.get("mode") == "gesture":
                    detector.prepare_gesture(owner)
                rover.set_mode(owner, payload.get("mode", "manual"))
            else:
                return jsonify(error="Unknown rover action."), 404
        except RoverConnectionError as exc:
            app.logger.warning("Rover connection failed: %s", exc.__cause__ or exc)
            return jsonify(error=str(exc)), 503
        except (ValueError, ImportError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            app.logger.exception("Rover action failed")
            return jsonify(error="Could not start that control. Check the laptop connection, dependencies, and setup guide."), 503
        return jsonify(**rover.status(owner), demo_mode=session.get("demo_mode", False))

    @app.get("/api/rover/camera")
    def camera():
        owner = session.get("pilot_token")
        if not rover.status(owner)["owned"]:
            return jsonify(error="Connect as the active pilot to view the camera."), 403

        def frames():
            while rover.status(owner)["owned"] and rover.mode == "gesture":
                frame = rover.frame
                if frame:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                time.sleep(0.12)
        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.post("/api/collections")
    def collection():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        count = payload.get("count")
        category = payload.get("category")
        if type(count) is not int or not 1 <= count <= 1000 or not isinstance(category, str) or category not in {"trash", "recycling"}:
            return jsonify(error="Choose a category and enter 1–1,000 items."), 400
        item_name = payload.get("item_name", "")
        if not isinstance(item_name, str) or not 2 <= len(item_name.strip()) <= 80:
            return jsonify(error="Describe the item in 2–80 characters."), 400
        try:
            request_id = str(uuid.UUID(str(payload.get("request_id", ""))))
        except ValueError:
            return jsonify(error="A valid collection request ID is required."), 400
        added = db.add_collection(g.user["id"], category, count, request_id, item_name.strip())
        return jsonify(saved=added, stats=db.stats(g.user["id"])), 201 if added else 200

    @app.post("/api/bin-events")
    def bin_event():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected a JSON object."), 400
        user_id, count = payload.get("user_id"), payload.get("count", 1)
        category, item_name = payload.get("category"), payload.get("item_name", "")
        if type(user_id) is not int or user_id < 1 or not db.user(user_id):
            return jsonify(error="Supply the registered depositor's user_id."), 400
        if type(count) is not int or not 1 <= count <= 1000 or not isinstance(category, str) or category not in {"trash", "recycling"}:
            return jsonify(error="Supply a category and 1–1,000 items."), 400
        if not isinstance(item_name, str) or not 2 <= len(item_name.strip()) <= 80:
            return jsonify(error="Describe the item in 2–80 characters."), 400
        try:
            request_id = str(uuid.UUID(str(payload.get("request_id", ""))))
        except ValueError:
            return jsonify(error="A valid event UUID is required. Reuse it for retries."), 400
        added = db.add_collection(user_id, category, count, request_id, item_name.strip())
        return jsonify(saved=added, stats=db.stats(user_id)), 201 if added else 200

    @app.errorhandler(404)
    def missing(_error):
        return render_template("error.html", message="This route is off the map."), 404

    @app.errorhandler(413)
    def too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Choose an image smaller than 8 MB."), 413
        return render_template("error.html", message="This upload is too large. Choose a smaller image."), 413

    @app.errorhandler(500)
    def server_error(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Could not save that action. Check the database connection and retry."), 500
        return render_template("error.html", message="We could not load this page. Check the database connection and try again."), 500

    if __package__:
        from .companion import mount_companion
    else:
        from companion import mount_companion
    mount_companion(app, pilot_user)
    if __package__:
        from .gemini_guide import mount_gemini_guide
    else:
        from gemini_guide import mount_gemini_guide
    mount_gemini_guide(app)
    return app


def main():
    parser = argparse.ArgumentParser(description="Litter-ally Trash — unified dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--init-db", action="store_true", help="Create the accounts and collection tables, then exit")
    args = parser.parse_args()
    app = create_app({"CLASSIFIER_AUTOLOAD": False} if args.init_db else None)
    if args.init_db:
        app.extensions["database"].initialize()
        app.extensions["classifier"].close()
        app.extensions["rover"].close()
        print("Litter-ally Trash database initialized.")
        return
    from waitress import serve
    print(f"Litter-ally Trash: http://{args.host}:{args.port}")
    print("Storage: " + ("TigerData PostgreSQL" if app.extensions["database"].is_tiger else "local development SQLite"))
    try:
        serve(app, host=args.host, port=args.port, threads=8)
    finally:
        app.extensions["classifier"].close()
        app.extensions["rover"].close()


if __name__ == "__main__":
    main()
