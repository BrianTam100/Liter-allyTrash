# Smart Trash Detector

## Browser interface

Run the web UI with the same Python environment as the classifier:

```sh
python web_server.py
```

Open **http://localhost:8000**. The page shows model loading progress, the detected
item, relative match scores, top candidates, and inference time. Choose this
device's browser camera, a camera connected to the Python server, or a photo
upload. Camera mode confirms labels with two successive readings. The connected
camera stays open and streams a mirrored preview independently of predictions,
targeting up to 30 frames per second. Actual frame rate depends on the camera and
machine. Inference uses the latest original frame without queuing old frames.
No additional Python dependencies are needed beyond `requirements.txt`.

To view a Pi's interface from another device on your trusted local network:

```sh
python web_server.py --host 0.0.0.0 --port 8000
```

Open `http://<pi-ip-address>:8000`. Use **Mac / Pi connected camera** for a USB
camera attached to the Pi (`--camera 1` selects another camera), or upload a photo.
Browser webcam access requires localhost or HTTPS, so it is unavailable on an
ordinary HTTP Pi network address.

To use a phone or laptop's own camera over Wi-Fi, serve HTTPS with a self-signed
certificate (replace the IP with the server's address):

```sh
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout key.pem -out cert.pem \
  -subj "/CN=trash-lens" -addext "subjectAltName=IP:192.168.1.50"
python web_server.py --host 0.0.0.0 --cert cert.pem --key key.pem
```

On the other device, open `https://192.168.1.50:8000`, accept the browser's
certificate warning, choose **This device’s camera**, and allow camera access.
Keep `key.pem` private. Ribbon-connected Pi cameras may require a
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
The three leading candidates are shown underneath, including when the result is
uncertain. Background classes and a low-detail image check reduce forced guesses.
If two close matches belong to the same object family, the display uses their
broader name (such as cardboard box or plastic bottle) instead of guessing a subtype.
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
Unknown items can still be misidentified; the "unsure" thresholds are heuristics.
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
