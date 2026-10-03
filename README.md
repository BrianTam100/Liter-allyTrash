# Smart Trash Detector

## Browser interface

Run the web UI with the same Python environment as the classifier:

```sh
.venv/bin/python web_server.py
```

Create `.venv` using the setup instructions below before the first run. On this
Mac, it is already configured with the Miniconda dependencies. The macOS system
`python3` does not have these packages and fails with `No module named 'cv2'`;
use `.venv/bin/python`, or activate the environment with `source .venv/bin/activate`.

Open **https://localhost:8000**. The page shows model loading progress, the detected
item, relative match scores, top candidates, and inference time. Choose this
device's browser camera, a camera connected to the Python server, or a photo
upload. Camera mode confirms labels with two successive readings. The connected
camera stays open and streams a mirrored preview independently of predictions,
targeting up to 30 frames per second. Actual frame rate depends on the camera and
machine. Inference uses the latest original frame without queuing old frames.
No additional Python dependencies are needed beyond `requirements.txt`.

The server listens on your local network over HTTPS by default and prints its
Wi-Fi address at startup. Browsers only allow camera access over HTTPS, so this
lets a phone or laptop on the same Wi-Fi use its own camera. On first start the
server creates a local certificate authority (`ca.pem`, `ca-key.pem`) with
`openssl`, and signs a `cert.pem` for the current Wi-Fi address with it. A new
certificate is signed automatically when the address changes.

To avoid the browser's certificate warning, trust `ca.pem` once on each device.
It is served at `https://<server-ip>:8000/ca.crt` (accept the warning one last
time to download it). The CA can only sign certificates for `localhost` and
private network addresses, so it cannot be used to impersonate real websites.
Keep `ca-key.pem` private.

- **This Mac:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.pem`
- **Firefox (any computer):** Settings → Privacy & Security → Certificates →
  View Certificates → Authorities → Import, choose the file, and check
  *Trust this CA to identify websites*.
- **iPhone / iPad:** open the `/ca.crt` link in Safari and allow the profile
  download. Install it in Settings → General → VPN & Device Management, then turn
  it on in Settings → General → About → Certificate Trust Settings.
- **Android:** Settings → Security → Encryption & credentials → Install a
  certificate → CA certificate, and choose the downloaded file.

Then open the printed `https://<server-ip>:8000`, choose **This device’s camera**,
and allow camera access. Use **Mac / Pi connected camera** for a USB camera
attached to the server (`--camera 1` selects another camera), or upload a photo.

### Trash can lid servo (Raspberry Pi)

When the live camera confirms a **Trash** item on two readings in a row, the server
opens the lid servo. The lid stays open while trash is still in view and closes
`--lid-seconds` (default 5) after the last trash reading. Recyclable items and
uploaded photos do not open the lid.

The servo is driven by a PCA9685 board at I2C address 0x40 on bus 1 (SDA = pin 3,
SCL = pin 5). Enable I2C with `sudo raspi-config` → Interface Options → I2C, and
install `sudo apt install python3-smbus i2c-tools` (`i2cdetect -y 1` should list
`40`). Options: `--lid-channel` (default: all 16 channels), `--lid-open-us`
(default 1944), `--lid-closed-us` (default 1167), and `--no-lid`. Without I2C,
for example on a Mac, the server prints "Lid servo disabled" and runs normally.

Pass `--host 127.0.0.1` to keep it private to this machine, `--http` to serve
plain HTTP, or `--cert` and `--key` to use your own certificate.
Ribbon-connected Pi cameras may require a
Picamera2 capture adapter; this interface currently uses OpenCV camera capture.
The server has no authentication: use it only on a trusted network, not the public
internet. All inference runs on the Python server, and inputs are not saved.
The model downloads on first use and can use its local cache afterward.
The web UI does not accelerate CLIP; Pi prediction speed needs hardware testing.

## Desktop interface

On this Mac, run `python classifier.py` with Miniconda Python, or choose **Run classifier** in VS Code.
Hold one item inside the green box against a plain background. Press Q to quit.
Try `--camera 1` if your preferred camera is not camera 0.

This demo uses pretrained CLIP ViT-B/16 to compare the image to 289 names in `trash_items.json`.
It can suggest specific names such as banana peel, apple core, soda can, or candy
wrapper without separately training those classes. Adding a name to the JSON list
adds a candidate; it does not guarantee reliable recognition of that item.

The updated version uses finer image patches than the previous ViT-B/32 model,
averages three text descriptions per item, and includes expanded non-food items
such as stationery, toiletries, tools, packaging, batteries, and electronics.
The live camera requires two consecutive accepted readings before showing an item
name. When the item changes, it clears the previous name while checking the new one.
The three leading candidates are shown underneath. When the match is weak or
close, the result uses the most probable item instead of asking for another
angle. Background classes and a low-detail image check still avoid naming an item
when none is shown. If two close matches belong to the same object family, the
display uses their broader name (such as cardboard box or plastic bottle).

Each result is labeled **Recyclable** or **Trash**, decided by the most probable
item. Recyclable items are listed in `recyclable_items.json`; every other item in
`trash_items.json` is trash. Items under `drop_off` (batteries, electronics,
plastic bags, paint) are recyclable at a drop-off site, not in the curbside bin,
and the web UI says so. Edit the lists to match your local recycling rules.
These changes are intended to improve recognition; no accuracy percentage is
claimed for the expanded catalog or your webcam conditions.

## Setup on another machine

Use a Python environment with the packages in `requirements.txt`:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python classifier.py --setup
.venv/bin/python classifier.py
```

The first setup downloads model weights (roughly 600 MB) from Hugging Face into
`.model-cache`. After setup, cached inference runs locally without uploading frames.
For an explicitly offline run, use
`HF_HUB_OFFLINE=1 python classifier.py`.

## Demo limitations

This is classification of the center crop, not multi-object detection. The box
is a placement guide, not a detected object boundary. Relative match scores compare
the listed candidates and are not probabilities that a prediction is correct.
Unknown items can still be misidentified, and because the most probable item is
always used, a weak match is shown rather than flagged as unsure.
Test your actual demo objects and lighting before presenting. Material type and
local disposal rules cannot reliably be inferred from appearance alone.

To classify a saved photo: `python classifier.py --image photo.jpg`.
The older custom TensorFlow script is preserved as `classifier_tflite.py`; its
`model.tflite` and `labels.txt` are unchanged and are not used by the new script.

Model documentation: https://huggingface.co/openai/clip-vit-base-patch16

Run behavior checks with `python -m unittest test_classifier.py`.
`recognition_check.json` records a small before/after diagnostic using the first
three resized photos in each of TrashNet's cardboard, glass, metal, paper, and
plastic categories. It is not a representative accuracy benchmark. Source:
https://github.com/garythung/trashnet (Gary Thung and Mindy Yang, MIT license).
