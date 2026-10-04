# Litter-ally Trash

A laptop-hosted website for the BRH_Test rover, with accounts, disposal history,
recycling rewards, an AI detection log, and keyboard/touch, Grok voice, and hand controls.
The classifier in `web` and the BRH_Test application share one dashboard, login,
and database. Browser assets now live in the repository-level `web` directory.
The original desktop scripts still work independently. Run either the desktop controller or the website at a time,
because both use the same Bluetooth COM port.

## Start the website

From the repository root, use a Python 3.11 environment:

```powershell
python -m venv BRH_Test/.venv
.\BRH_Test\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
Copy-Item BRH_Test/.env.example BRH_Test/.env  # first setup only
.\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --no-lid
```

Open **http://localhost:8000**. No account is needed: every visitor records drops as one shared local pilot.
`BRH_Test/website.py` also serves this same dashboard with Waitress over HTTP.
Without `DATABASE_URL`, accounts use the persistent **local development** SQLite
database in `BRH_Test/.instance/`. The interface labels this mode. Local records
are not uploaded or migrated automatically to TigerData when you switch.

Recognition prepares in the background, downloading CLIP weights on first use.
Pass `--no-model-load` to defer this, then use **Prepare scanner** on the dashboard.
Manual drops, rankings, and rover controls work while the model loads.
`requirements-dashboard.txt` includes both recognition and laptop control dependencies.
The smaller `requirements-web.txt` is only sufficient for the account/control
modules and their isolated tests; the unified website also needs CLIP/Pillow.

## Connect TigerData

1. Create or select a PostgreSQL service in Tiger Cloud. Copy its connection URL
   from the service's connection screen into `DATABASE_URL` in `BRH_Test/.env`.
2. Include TLS, for example:
   `postgresql://tsdbadmin:PASSWORD@HOST:PORT/tsdb?sslmode=require`.
   The application requires TLS and preserves stricter verification modes.
3. Set `SECRET_KEY` to a long random value. Generate one with:
   `python -c "import secrets; print(secrets.token_hex(32))"`.
4. From the repository root, run `python web_server.py --init-db`, then start the dashboard.

Initialization creates only `lt_users`, `lt_collections`, and `lt_detections`, plus their indexes.
Rerun `--init-db` after upgrading so an existing TigerData database gets `lt_detections`.
Accounts, individual disposal records, and AI detections live in your TigerData
database. Email addresses and password hashes are never shown on the site.
Queries use parameters. These ordinary PostgreSQL tables do not need a TimescaleDB
hypertable for this project size.

See [TigerData documentation](https://www.tigerdata.com/docs/get-started) and
[Psycopg's parameterized query guide](https://www.psycopg.org/psycopg3/docs/basic/usage.html).

The `.env`, `.instance/`, and `.venv/` directories are ignored. Do not put the
database URL or API secrets in browser code.

## Recycling rewards and attribution

- Every recycled item earns **10 points**. Trash is tracked and earns **0 points**.
- The detection log records each final AI reading (one per item in a live scan,
  one per photo) and links it to the drop it was confirmed as, if any.
- All time, rolling 30-day, and rolling 7-day rankings are available.
- Each event records **who**, **what item**, **which bin**, **how many**, and **when**.
- Signed-in manual entries always belong to that account. Pilot IDs are shown
  on the dashboard. UUIDs make event submissions idempotent, including retries.
- Points are recognition; prize redemption and physical rewards are not implemented.

### Submit real bin events from the Raspberry Pi

Set `COLLECTION_API_KEY` to the same random secret on the website and Pi. On the Pi,
use `LITERALLY_TRASH_URL=http://LAPTOP_LAN_IP:8000` to target the laptop. Start the
website with `python web_server.py --host 0.0.0.0 --http` for this HTTP LAN example.
For HTTPS, see the repository README. Use the correct trusted CA certificate on
the Pi; the event client uses standard Python TLS verification.

```bash
export COLLECTION_API_KEY="your-random-secret"
export LITERALLY_TRASH_URL="http://LAPTOP_LAN_IP:8000"
python bin_event_client.py --user-id 1 --item "Plastic bottle" --category recycling
```

Alternatively import `post_bin_event` into the bin's detection code:

```python
from bin_event_client import post_bin_event

# event_id must be stored/reused by the caller when retrying a detected deposit.
post_bin_event(website_url, api_key, identified_user_id,
               "Aluminum can", "recycling", event_id=event_id)
```

`POST /api/bin-events` requires `Authorization: Bearer COLLECTION_API_KEY` and JSON:

```json
{
  "user_id": 1,
  "item_name": "Aluminum can",
  "category": "recycling",
  "count": 1,
  "request_id": "d3c63c6e-8cb8-46ad-a652-93063b63dc11"
}
```

The account must exist. The bin hardware must identify the person (for example,
an account-linked badge or scanner) and classify the deposit before calling this
endpoint. The unified scanner fills the signed-in person's drop form, and its
confirmation records the server's recognized item/bin. Each live item lock gets
a single scan ID, so repeated frames and confirmation retries cannot add points
again. A scan expires after five minutes. Photos do not move lids or award points
automatically. Recognition does not verify a physical deposit or identify the
person; confirmed and manual drops are self-reported.

## Connect and drive the rover

Open **Rover controls**, choose Bluetooth or Wi-Fi, and click **Connect rover**.
No motors, cameras, or microphones activate just by opening a page. The connected
scanner and hand tracker coordinate ownership of camera 0; enabling hand tracking
releases your own scan or rejects a camera another person is using.

Hold W/S to drive forward/backward, A/D to spin, and Z/C to strafe left/right.
Release a direction to stop, or press Space/Esc to stop all motion.
For Z/C support on existing hardware, upload the updated `driveController.ino`
to the Arduino and copy the updated `motor_control.py` to the Pi for Wi-Fi.

### Bluetooth

Pair laptop/Pi and follow `README.md` to enable RFCOMM. Run
`motor_control_bluetooth_camera.py` on the Pi. Choose the rover's COM port in the
**Port** menu on Rover controls; each browser remembers its choice. **Auto** uses
`ROVER_SERIAL_PORT` from `.env` (default `auto`: the one paired outgoing Bluetooth port).
The baud rate defaults to `115200`. The port stays open after you disconnect, so
reconnecting is instant; only the first connection waits for Windows to open the link.
The website sends the same `w`, `a`, `s`, `d`, `z`, `c`, `x` bytes and newline-terminated
hand angles as `command_bluetooth_camera.py`.

If opening a port fails with Windows error **1256** ("The remote system is not
available"), Windows cannot reach the remote Bluetooth device through that port.
The website returns HTTP 503 and keeps the rover offline; later status requests
returning HTTP 200 only mean the website itself is responding.

1. Power on the Pi, keep it in range, and enable Bluetooth on both devices.
2. Check **Bluetooth settings > More Bluetooth settings > COM Ports** on Windows.
   Set `ROVER_SERIAL_PORT` in `BRH_Test/.env` to the Pi's **Outgoing** port, then
   restart the website. Listing a port does not prove the Pi is reachable:
   `.\BRH_Test\.venv\Scripts\python.exe -m serial.tools.list_ports -v`.
3. On the Pi, complete the Serial Port Profile setup in [README.md](README.md).
   Keep `sudo rfcomm watch 0 1` running in one terminal; in another, run
   `sudo python3 motor_control_bluetooth_camera.py` from its directory.
4. Close desktop rover controllers and serial monitors, then retry **Connect rover**.
   If the pairing is stale, remove and pair the Pi again and recheck the outgoing
   port number.

### Wi-Fi

Set `PI_IP` and `PI_UDP_PORT` (default `5005`), and run `motor_control.py` on the Pi.
The Wi-Fi receiver now uses Arduino baud **115200**, matching the checked-in
Arduino sketch and Bluetooth receiver. Copy the updated receiver to the Pi and
restart it if it still has the older 9600-baud version.
The Wi-Fi receiver accepts WASD, Z/C, and stop, so hand angles require Bluetooth.
UDP provides no acknowledgement; the interface says the target is set rather
than claiming the Pi confirmed a connection.

### Control modes

| Control | Behavior |
| --- | --- |
| Keyboard | Hold WASD or arrows; release to stop. Space/Escape stops all modes. |
| Touch/mouse | Hold a pad button; release or cancel to stop. Buttons also support Enter/Space. |
| Grok voice | Set `XAI_API_KEY`; enable voice to use existing `voice_control.py` on the laptop. |
| Hand gestures | Enable camera tracking on the laptop; wrist/index angle controls strafing. No hand means stop. |

The existing gesture code requires `mediapipe.solutions.hands`, so the website
requirements pin the compatible `mediapipe==0.10.21` on Python 3.11. Enable a mode
only when its hardware and, for voice, API key are available.

Manual controls have priority. Stop all motion disables assistance. The bridge
holds one pilot lease, stops a stale manual command after 0.7 seconds, and stops
and disconnects if the browser heartbeat expires after 1.5 seconds. Control epochs
and monotonic sequences reject late movement requests after release or stop.
Leaving the page or hiding/unfocusing the window releases control.

These software stops rely on the laptop's link reaching the Pi. A broken radio
link can prevent delivery; the existing Arduino holds its last command and has
no firmware watchdog. Keep the rover in view. A hardware-side watchdog would be
needed for guaranteed stopping after a lost connection.

## Running beyond localhost

`BRH_Test/website.py` binds to localhost by default. `web_server.py` defaults to
LAN HTTPS; use `--host 127.0.0.1 --http` for local development. For HTTPS hosting,
place this laptop service behind
an HTTPS reverse proxy and set `COOKIE_SECURE=true`. Set a stable `SECRET_KEY` and
use TigerData for durable shared accounts. Run one server process per physical
rover: its pilot lease and transport ownership live in memory. The application
does not publish itself or expose the laptop automatically.

## Verify

```powershell
python -m unittest test_classifier test_web_server test_dashboard
python -m unittest discover -s BRH_Test -p test_website.py
```

Run these commands from the repository root. The tests use temporary local databases and simulated serial hardware. They cover
accounts, CSRF, recycling-only ranking, ties, disposal attribution, retry
deduplication, escaping, command priority, late packets, and automatic stopping.
TigerData credentials and real rover hardware are needed for end-to-end checks
against those services.
