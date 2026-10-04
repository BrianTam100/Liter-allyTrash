# Architecture

Three computers work together. The **laptop** does the heavy lifting (AI model,
website, database). The **Raspberry Pi** rides on the rover and relays commands to
the hardware. The **Arduino** drives the motors.

```
                 Browser(s)  http://localhost:8000  (or the laptop's LAN IP)
                     │  pages, /api/*
                     ▼
┌──────────────────────── LAPTOP ────────────────────────┐
│ web_server.py ── BRH_Test/website.py (Flask app)        │
│   ├─ dashboard_classifier.py → classifier_service.py    │
│   │     └─ classifier.py (CLIP model, GPU if available) │
│   ├─ BRH_Test/rover_bridge.py (drive commands)          │
│   ├─ BRH_Test/voice_control.py (Grok voice, optional)   │
│   ├─ lid.py RemoteLid (lid commands)                    │
│   └─ BRH_Test/database.py (SQLite or TigerData)         │
└───┬──────────────┬──────────────┬──────────────┬────────┘
    │ Bluetooth    │ Wi-Fi UDP    │ Wi-Fi UDP    │ HTTP MJPEG
    │ serial (COMx)│ :5005 drive  │ :5006 lids   │ :8080 camera
    ▼              ▼              ▼              ▲
┌──────────────────── RASPBERRY PI (on the rover) ───────────────────┐
│ motor_control_bluetooth_camera.py  (/dev/rfcomm0 → Arduino)        │
│ motor_control.py                   (UDP :5005   → Arduino)         │
│ lid_server.py → lid.py             (PCA9685 servo board over I2C)  │
│ pi_camera.py                       (camera → MJPEG stream :8080)   │
└──────────────┬────────────────────────────────────────────────────┘
               │ USB serial /dev/ttyACM0, 115200 baud
               ▼
      ARDUINO + CNC shield → 4 stepper motors (mecanum wheels)
      BRH_Test/driveController/driveController.ino
```

## The main flows

**Driving.** The browser holds a drive key and posts `/api/rover/command` about every
160 ms. `rover_bridge.py` sends one byte (`w` `a` `s` `d` `x`) over Bluetooth serial,
or as a UDP packet over Wi-Fi. The Pi forwards it unchanged to the Arduino.
Hand-gesture mode sends an angle instead (`"90\n"` = forward), and only over Bluetooth.

**Safety rules in `rover_bridge.py`:**
- Only one browser drives at a time; others see "Someone else is driving".
- The browser must send a heartbeat; after 1.5 s of silence the rover stops and is released.
- A held key stops 0.7 s after the last command, even if heartbeats continue.
- Releasing a key, Stop all motion, or changing mode sends `x`, and late packets are
  ignored (epoch and sequence numbers).

**Scanning.** The scanner gets frames from the browser's camera, a photo upload, or
the server camera (laptop webcam or the Pi stream given by `--camera`).
`classifier.py` scores each frame with CLIP. Live scans compare 3 readings, then
**lock** onto one item. The lock holds until 2 empty readings or 4 readings of a
different item (`ItemLock` in `classifier_service.py`). While an item is locked, and
lids are enabled, the matching lid opens over UDP and stays open about 5 s after the
last reading.

**Logging and points.** Every locked live reading (once per item) and every photo is
written to `lt_detections`. When someone confirms the drop, a row goes into
`lt_collections`, linked by the same `scan_id`. Recycling earns 10 points per item.
The Pi can also post sensor-verified drops to `/api/bin-events` with a shared API key.

## Ports and addresses

| What | Where | Port | Set by |
|------|-------|------|--------|
| Website | laptop | 8000 | `web_server.py --port` |
| Drive over Wi-Fi | Pi | UDP 5005 | `PI_IP`, `PI_UDP_PORT` in `BRH_Test/.env` |
| Lids | Pi | UDP 5006 | `--lid-host`, `--lid-port` / `LID_HOST` |
| Pi camera stream | Pi | 8080 (`/stream.mjpg`) | `--camera http://<pi-ip>:8080/stream.mjpg` |
| Drive over Bluetooth | laptop COM port | n/a | **Port** menu on Rover controls; `ROVER_SERIAL_PORT` (default `auto`) |

## Website pages

- **Dashboard (`/`):** stats, scanner, record a drop, latest detections, recent drops.
- **Rover controls (`/controls`):** connection and port, drive pad, keyboard/voice/gesture modes.
- **Detection log (`/log`):** every AI detection, plus breakdowns by bin and by item.

Everyone shares a single "Pilot" account (no login). Each browser gets its own
session token, which is what decides who is driving.

## Code map

| Path | Role |
|------|------|
| `web_server.py` | Main entry point: certificates/HTTPS, camera choice, lids, starts the server (Waitress for `--http`) |
| `BRH_Test/website.py` | Flask app: pages, rover API, drops API, Pi bin-event API, security headers |
| `dashboard_classifier.py` | Scanner API: start/stop/heartbeat, predict, confirm, detection logging |
| `classifier_service.py` | Camera capture thread, `ItemLock` (stable readings), lid triggering |
| `classifier.py` | CLIP model, item lists, the 4 `TARGETS` the demo reports |
| `trash_items.json`, `recyclable_items.json` | Labels the model compares; which are curbside or drop-off |
| `BRH_Test/rover_bridge.py` | Drive link, port detection, ownership and heartbeat safety |
| `BRH_Test/database.py` | Tables `lt_users`, `lt_collections`, `lt_detections` |
| `web/` | Shared static files and the dashboard template (`index.html`, `scanner.html`, `app.js`, `style.css`) |
| `BRH_Test/website/templates/` | Other pages (`base.html`, `controls.html`/`rover.html`, `detections.html`) |
| `lid.py`, `lid_server.py`, `calibrate_lids.py`, `servo_calibration.json` | Lid servos (Pi side) |
| `pi_camera.py` | Pi camera stream |
| `BRH_Test/command*.py`, `motor_control*.py` | Older desktop/Pi scripts; still work, but don't run them alongside the website |
| `classifier_tflite.py`, `model.tflite`, `labels.txt`, `*_previous.py` | Earlier model experiments, not used by the website |

## Database

The website uses `DATABASE_URL` from `BRH_Test/.env` if it's set (TigerData/Postgres),
and a local SQLite file in `BRH_Test/.instance/` otherwise. SQLite tables are created
automatically. **On TigerData, run `python web_server.py --init-db` after pulling new
code** so new tables (such as `lt_detections`) exist.
