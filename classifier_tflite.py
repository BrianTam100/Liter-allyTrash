import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import tensorflow as tf

parser = argparse.ArgumentParser(description="Run the webcam classifier.")
parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
args = parser.parse_args()
project_dir = Path(__file__).resolve().parent

# 1. Load the model and labels
interpreter = tf.lite.Interpreter(model_path=str(project_dir / "model.tflite"))
interpreter.allocate_tensors()

with open(project_dir / "labels.txt", "r") as f:
    labels = []
    for line in f:
        label = line.strip()
        if not label:
            continue
        # Exports often prefix each class name with its numeric index.
        parts = label.split(maxsplit=1)
        labels.append(parts[1] if len(parts) == 2 and parts[0].isdigit() else label)

# Get model requirements
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
height = input_details[0]['shape'][1]
width = input_details[0]['shape'][2]
is_quantized = input_details[0]['dtype'] == np.uint8
if len(labels) != int(output_details[0]['shape'][-1]):
    raise SystemExit("labels.txt must contain one name per model class, in training order.")
generic_labels = all(label.lower().startswith("class ") for label in labels)

# 2. Open the Mac webcam
backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
cap = cv2.VideoCapture(args.camera, backend)
camera_help = (
    "Check System Settings > Privacy & Security > Camera and allow the app "
    "running Python (such as VS Code or Terminal), then restart that app. "
    "Close other apps using the camera. If you have multiple cameras, "
    "try: python classifier.py --camera 1"
)
if not cap.isOpened():
    cap.release()
    raise SystemExit(f"Could not open camera {args.camera}. {camera_help}")

print(f"Waiting for camera {args.camera}...", flush=True)
last_frame_time = time.monotonic()
camera_error = None

while True:
    ret, frame = cap.read()
    if not ret or frame is None or frame.size == 0:
        # Some cameras need time to start delivering frames.
        if time.monotonic() - last_frame_time < 5:
            time.sleep(0.1)
            continue
        camera_error = (
            f"Camera {args.camera} opened but supplied no frames for 5 seconds. "
            f"{camera_help}"
        )
        break
    last_frame_time = time.monotonic()

    # 3. Process the frame to match what the model expects
    img = cv2.resize(frame, (width, height))
    img = np.expand_dims(img, axis=0)
    
    if not is_quantized:
        img = (np.float32(img) / 127.5) - 1.0

    # 4. Predict
    interpreter.set_tensor(input_details[0]['index'], img)
    interpreter.invoke()
    predictions = interpreter.get_tensor(output_details[0]['index'])[0]
    
    # 5. Display the highest confidence result
    top_index = np.argmax(predictions)
    confidence = float(predictions[top_index])
    if np.issubdtype(output_details[0]['dtype'], np.integer):
        scale, zero_point = output_details[0]['quantization']
        confidence = (confidence - zero_point) * scale
    label_text = f"Detected: {labels[top_index]}"

    # Put the result on a separate banner so it stays readable on any background.
    display_width = max(640, frame.shape[1])
    display_height = round(frame.shape[0] * display_width / frame.shape[1])
    preview = cv2.resize(frame, (display_width, display_height))
    banner = np.full((130, display_width, 3), (30, 30, 30), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_width = cv2.getTextSize(label_text, font, 1.0, 2)[0][0]
    font_scale = min(1.0, (display_width - 40) / max(text_width, 1))
    cv2.putText(banner, label_text, (20, 40), font, font_scale, (80, 255, 120), 2, cv2.LINE_AA)
    cv2.putText(banner, f"Confidence: {confidence:.0%}", (20, 76), font, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    hint = "Name your trained classes in labels.txt" if generic_labels else "Press Q to quit"
    cv2.putText(banner, hint, (20, 110), font, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.imshow("Mac Trash Classifier", np.vstack((banner, preview)))

    # Press 'q' to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
if camera_error:
    raise SystemExit(camera_error)
