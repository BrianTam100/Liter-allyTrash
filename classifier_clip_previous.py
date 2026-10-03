"""Recognize one common trash item at a time using pretrained CLIP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HOME", str(ROOT / ".model-cache"))

import cv2
import numpy as np

MODEL_ID = "openai/clip-vit-base-patch32"
BACKGROUND = ["an empty table with no object", "an empty hand", "a person with no trash", "a room with no trash item"]


class TrashClassifier:
    def __init__(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        self.labels = json.loads((ROOT / "trash_items.json").read_text())
        if not self.labels or len(set(self.labels)) != len(self.labels):
            raise ValueError("trash_items.json must contain unique item names.")
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        local_model = ROOT / ".model-cache" / "ready-model"
        cached = (local_model / "config.json").exists() and (local_model / "model.safetensors").exists()
        source = str(local_model) if cached else MODEL_ID
        print(f"Loading {MODEL_ID} on {self.device}" + (" from local files." if cached else "; downloading model files."), flush=True)
        self.processor = CLIPProcessor.from_pretrained(source, use_fast=False)
        self.model = CLIPModel.from_pretrained(source, use_safetensors=True).eval()
        if not cached:
            self.processor.save_pretrained(local_model)
            self.model.save_pretrained(local_model)
        self.model = self.model.to(self.device)
        prompts = [f"a photo of {name}" for name in self.labels + BACKGROUND]
        tokens = self.processor(text=prompts, return_tensors="pt", padding=True).to(self.device)
        with torch.inference_mode():
            features = self.model.get_text_features(**tokens)
            self.text_features = features / features.norm(dim=-1, keepdim=True)

    def predict(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            features = self.model.get_image_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
            similarities = (features @ self.text_features.T)[0]
            scores = (similarities * self.model.logit_scale.exp()).softmax(dim=0)
            values, indices = scores.topk(2)
        index = int(indices[0])
        score, second = float(values[0]), float(values[1])
        # Demo heuristics, not calibrated probabilities of correctness.
        if index >= len(self.labels):
            label = "No trash item detected"
        elif score < 0.25 or score - second < 0.08 or float(similarities[index]) < 0.20:
            label = "Unsure - move item closer"
        else:
            label = self.labels[index]
        return label, score


def center_box(frame):
    height, width = frame.shape[:2]
    size = int(min(height, width) * 0.8)
    return (width - size) // 2, (height - size) // 2, size


def render(frame, label, score):
    x, y, size = center_box(frame)
    preview = frame.copy()
    cv2.rectangle(preview, (x, y), (x + size, y + size), (80, 255, 120), 2)
    width = 800
    preview = cv2.resize(preview, (width, round(frame.shape[0] * width / frame.shape[1])))
    banner = np.full((140, width, 3), 30, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    title = f"Detected: {label}"
    text_width = cv2.getTextSize(title, font, 1, 2)[0][0]
    scale = min(1.0, (width - 40) / max(text_width, 1))
    cv2.putText(banner, title, (20, 40), font, scale, (80, 255, 120), 2, cv2.LINE_AA)
    detail = "Starting recognition..." if score is None else f"Relative match: {score:.0%} (not certainty)"
    cv2.putText(banner, detail, (20, 80), font, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(banner, "Hold ONE item inside the box | Q to quit", (20, 117), font, 0.65, (200, 200, 200), 1, cv2.LINE_AA)
    return np.vstack((banner, preview))


def run_camera(classifier, camera):
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    cap = cv2.VideoCapture(camera, backend)
    window = "Smart Trash Detector"
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {camera}. Allow Camera access for your terminal or IDE in System Settings, or try --camera 1.")
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        last_frame = time.monotonic()
        last_prediction = 0.0
        label, score = "Waiting for item", None
        future = None
        # Keep the video responsive while inference runs.
        with ThreadPoolExecutor(max_workers=1) as worker:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    if time.monotonic() - last_frame > 5:
                        raise RuntimeError("Camera supplied no frames for 5 seconds. Check camera permissions and close other camera apps.")
                    if cv2.waitKey(30) & 0xFF == ord("q"):
                        break
                    continue
                last_frame = time.monotonic()
                if future is not None and future.done():
                    label, score = future.result()
                    future = None
                if future is None and time.monotonic() - last_prediction >= 0.35:
                    x, y, size = center_box(frame)
                    future = worker.submit(classifier.predict, frame[y:y + size, x:x + size].copy())
                    last_prediction = time.monotonic()
                cv2.imshow(window, render(frame, label, score))
                if cv2.waitKey(1) & 0xFF == ord("q") or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--setup", action="store_true", help="Download/load the model without opening the camera")
    parser.add_argument("--image", type=Path, help="Classify a still image without opening the camera")
    args = parser.parse_args()
    try:
        classifier = TrashClassifier()
        if args.setup:
            print(f"Ready: {len(classifier.labels)} trash item names. Model cached for offline use.")
        elif args.image:
            frame = cv2.imread(str(args.image))
            if frame is None:
                raise ValueError(f"Cannot read image: {args.image}")
            label, score = classifier.predict(frame)
            print(f"Detected: {label} | Relative match: {score:.0%} (not certainty)")
        else:
            run_camera(classifier, args.camera)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Use your Miniconda Python: python classifier.py. Install dependencies with python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
