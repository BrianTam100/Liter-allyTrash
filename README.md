# Liter-ally Trash

One dashboard for joining the project, identifying waste, recording personal
recycling, earning points, reviewing what the AI detected, and driving the SortRover.
The original `web` classifier interface and `BRH_Test` account/control application
now run together, with shared login and navigation.

## Run the unified dashboard

Use Python 3.11. From the repository root on Windows:

```powershell
python -m venv BRH_Test/.venv
.\BRH_Test\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
Copy-Item BRH_Test/.env.example BRH_Test/.env  # first setup only; keep existing credentials
.\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --no-lid
```

Open **http://localhost:8000** and create your account. The existing
`BRH_Test/.venv` already has the dashboard dependencies installed on this machine.
If `python` is the Windows Store stub, use your Python 3.11/Conda interpreter to
create the environment. On macOS/Linux, the equivalent interpreter is
`BRH_Test/.venv/bin/python`.

Recognition loads in the background. First use downloads CLIP weights into
`.model-cache`; loading time and download size depend on the model. Use
`--no-model-load` to start immediately with scanning on standby, then select
**Prepare scanner** on the dashboard. No account is needed; manual drops, rewards, and rover
controls work while the model loads. Cameras and microphones only activate when
you select their controls.

The dashboard has three destinations:

- **Dashboard:** choose your browser camera, the connected/Pi camera, or a photo.
  Use a recognized item to fill the drop form, then confirm after putting it in
  the bin. Manual entries remain available. Your recent drops show who you are,
  what you deposited, the bin, quantity, and time.
- **Rover controls:** keyboard/arrows, touch/mouse, Grok voice, and hand gestures,
  using the existing Bluetooth and Wi-Fi protocols.
- **Detection log:** every AI detection with its bin, match score, camera source,
  and whether it was confirmed as a drop, plus breakdowns by bin and by item
  across all time or the past 7/30 days. Recycling earns **10 points per item**; trash earns **0**.

Camera frames never award points by themselves. A stable live reading has one
scan ID; retrying its confirmation cannot credit it twice. Recognition does not
verify a physical deposit or identify a person: the signed-in person confirms
the drop. Sensor-verified events can use the authenticated Pi event endpoint.
Prize redemption is not implemented.

## Accounts and TigerData

Configuration lives in **`BRH_Test/.env`**. Set `DATABASE_URL` to your Tiger Cloud
PostgreSQL connection string with `sslmode=require`, and set a long random
`SECRET_KEY`. Then initialize the application tables:

```powershell
.\BRH_Test\.venv\Scripts\python.exe web_server.py --init-db
```

Without `DATABASE_URL`, the dashboard uses the persistent SQLite development
database at `BRH_Test/.instance/literally-trash.db` and labels that mode in the
interface. Switching to TigerData does not migrate local accounts automatically.
Credentials stay on the Python server; public rankings expose pilot names only.
See [BRH_Test/WEBSITE.md](BRH_Test/WEBSITE.md) for accounts, configuration, controls,
and identified Pi disposal events.

## Cameras and recognition

The current classifier reports four sorted items, configured in `TARGETS` in
`classifier.py`: **plastic water bottle** and **cardboard** go to recycling;
**paper towel** and **chip bag** go to trash. Other objects produce no supported
item result; enter those manually after checking the correct bin.

Live recognition compares three readings, locks the best-supported label, and
holds it until two empty readings or four readings of a different item. The
connected camera captures a preview independently from inference. Actual speed
depends on the machine. Images are processed locally and are not stored.
Relative match scores compare model candidates; they are not accuracy probabilities.

The large CLIP model is the default. For a smaller model on Windows:

```powershell
$env:TRASH_MODEL = 'openai/clip-vit-base-patch16'
.\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --no-lid
```

Select **Connected / Pi camera** for a camera attached to the Python server.
`--camera 1` selects another USB camera. Hand tracking uses laptop camera 0;
the server prevents simultaneous scanner/gesture ownership of that camera.
The live scanner is owned by one signed-in session, and it stops on navigation,
page hiding, or heartbeat expiry. Other people can still upload photos.

To stream a Pi camera to the model computer, run on the Pi:

```sh
python3 pi_camera.py                 # Pi camera module; --usb 0 for USB webcam
```

Then run the dashboard with `--camera http://<pi-ip>:8080/stream.mjpg` and select
**Connected / Pi camera**. The Pi stream itself has no authentication, so keep
it on the project LAN.

## Phones, HTTPS, and LAN access

`web_server.py` defaults to LAN HTTPS on port 8000. Local HTTP is available with
`--host 127.0.0.1 --http`. Phones need HTTPS to use their own browser cameras;
connected camera and uploads also work over HTTP. If `openssl` is installed,
the server creates `ca.pem`/`ca-key.pem` and signs `cert.pem`/`key.pem` for localhost
and the current private LAN address. It prints the LAN URL. Pass `--cert` and
`--key` to supply your own certificate. HTTPS uses secure session cookies.

Trust the local CA once on each device, downloading it at
`https://<server-ip>:8000/ca.crt`. Keep `ca-key.pem` private.

- **Windows:** import `ca.pem` into your user's Trusted Root Certification Authorities.
- **macOS:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.pem`
- **Firefox:** Settings > Privacy & Security > Certificates > Authorities > Import.
- **iOS/iPadOS:** install the downloaded profile in Settings > General > VPN &
  Device Management, then enable trust in About > Certificate Trust Settings.
- **Android:** install it through the device's CA certificate settings.

Run one Python server process per physical rover/camera. For public hosting, use
an HTTPS reverse proxy and stable secrets; the Pi camera and UDP hardware services
are intended for a trusted LAN. `BRH_Test/website.py` remains an alternate local
Waitress entry point for the **same dashboard**, not a separate website.

## Pi bin lids

Lid automation is off by default. Enable it after configuring the Pi:

```powershell
.\BRH_Test\.venv\Scripts\python.exe web_server.py --enable-lid --lid-host <pi-ip>
```

Or set `CLASSIFIER_LID_ENABLED=true`, `LID_HOST`, and `LID_PORT` in `BRH_Test/.env`.
Omit the host to use LAN broadcast. `--no-lid` always disables commands.
Live locked readings send `open Trash` or `open Recyclable` to `lid_server.py`
over UDP port 5006. Photos and special drop-off items never open lids. Stopping
or losing the live session closes the lids; otherwise the Pi closes after its
configured hold period.

Copy `lid.py`, `lid_server.py`, `calibrate_lids.py`, and `servo_calibration.json`
to the Pi. The Pi needs I2C/SMBus, not the classifier model:

```sh
sudo apt install python3-smbus i2c-tools
sudo raspi-config nonint do_i2c 0
python3 lid_server.py
```

The PCA9685 is at address 0x40, I2C bus 1 (SDA pin 3, SCL pin 5): trash on
channel 0 and recycling on channel 3. Pulse calibration is in
`servo_calibration.json`. Stop the receiver before running `calibrate_lids.py`;
use `o`/`c` to save open/closed positions. `--lid-port` must match the Pi receiver.

## Code layout and verification

- `web/index.html`, `web/scanner.html`, `web/app.js`, `web/style.css`: dashboard and shared browser assets.
- `BRH_Test/website.py`, `database.py`, `rover_bridge.py`: shared accounts, rewards, and rover backend.
- `dashboard_classifier.py`: authenticated scanning, session ownership, and scan confirmation.
- `classifier_service.py`, `classifier.py`: camera capture, stable readings, and CLIP inference.
- `web_server.py`: unified startup and optional LAN TLS.

```powershell
.\BRH_Test\.venv\Scripts\python.exe -m unittest test_classifier test_web_server test_dashboard
.\BRH_Test\.venv\Scripts\python.exe -m unittest discover -s BRH_Test -p test_website.py
```

Tests use temporary databases and simulated hardware. Real Pi movement, camera
recognition quality, and the TigerData service still need their hardware/credentials.

The desktop classifier remains available: install `requirements.txt`, then run
`python classifier.py`, `python classifier.py --image photo.jpg`, or
`python classifier.py --setup` to prepare the model. It compares whole-frame
images, not multiple object bounding boxes. Test your demo objects and lighting;
appearance alone cannot establish material or local recycling rules.
`classifier_tflite.py`, `model.tflite`, and `labels.txt` preserve the older model.
Model: [CLIP ViT-L/14](https://huggingface.co/openai/clip-vit-large-patch14).
