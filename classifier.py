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

MODEL_ID = "openai/clip-vit-base-patch16"
BACKGROUND = ["an empty table with no object", "an empty hand", "a person with no trash", "a room with no trash item", "a computer screen", "a keyboard", "a wall", "a desk with many different objects"]
TEMPLATES = ["a photo of {}.", "a close-up photo of {}.", "a photo of someone holding {}."]
ALIASES = {
    "aluminum soda can": "an aluminum beverage can, a soda or beer can",
    "steel food can": "a tin can for canned food",
    "plastic water bottle": "a clear plastic drinking water bottle",
    "plastic soda bottle": "a plastic soft drink bottle with a soda label",
    "plastic food container": "a plastic takeaway food tub or container",
    "plastic yogurt cup": "a small yogurt pot or yogurt container",
    "potato chip bag": "a crinkled potato chip packet or crisps bag",
    "snack bar wrapper": "a granola bar or protein bar wrapper",
    "cardboard tube": "an empty toilet paper roll or paper towel tube",
    "broken headphones": "headphones or earphones",
    "old shoe": "a shoe or sneaker",
}
FAMILIES = {
    "cardboard box": {"cardboard box", "pizza box", "cereal box", "cardboard tissue box", "cardboard shoe box", "cardboard shipping mailer"},
    "glass bottle": {"glass bottle", "glass condiment bottle"},
    "glass jar": {"glass jar", "glass sauce jar", "glass jam jar", "glass candle jar"},
    "plastic bottle": {"plastic water bottle", "plastic soda bottle", "plastic squeeze bottle", "plastic milk jug", "plastic spray bottle", "plastic ketchup bottle", "plastic mustard bottle", "plastic dish soap bottle", "plastic hand soap bottle", "plastic lotion bottle", "plastic medicine bottle", "shampoo bottle", "laundry detergent bottle"},
    "paper": {"newspaper", "magazine", "sheet of paper", "paper envelope", "paper label", "paper business card", "postcard", "paper ticket", "receipt", "sticky note"},
    "battery": {"AA battery", "AAA battery", "9 volt battery", "coin cell battery"},
    "electrical cable": {"electrical cable", "USB cable"},
}


def common_family(first, second):
    return next((name for name, members in FAMILIES.items() if first in members and second in members), None)


class StablePrediction:
    """Require two successive accepted readings; clear old labels immediately."""
    def __init__(self):
        self.pending = None
        self.count = 0

    def update(self, label):
        if label.startswith(("Unsure", "No trash", "Hold", "Image")):
            self.pending, self.count = None, 0
            return label
        self.count = self.count + 1 if label == self.pending else 1
        self.pending = label
        return label if self.count >= 2 else "Hold still - checking item"


class TrashClassifier:
    def __init__(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.torch = torch
        self.labels = json.loads((ROOT / "trash_items.json").read_text())
        if not self.labels or len(set(self.labels)) != len(self.labels):
            raise ValueError("trash_items.json must contain unique item names.")
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        local_model = ROOT / ".model-cache" / "ready-model-patch16"
        cached = (local_model / "config.json").exists() and (local_model / "model.safetensors").exists()
        source = str(local_model) if cached else MODEL_ID
        print(f"Loading {MODEL_ID} on {self.device}" + (" from local files." if cached else "; downloading model files."), flush=True)
        self.processor = CLIPProcessor.from_pretrained(source, use_fast=False)
        self.model = CLIPModel.from_pretrained(source, use_safetensors=True).eval()
        if not cached:
            self.processor.save_pretrained(local_model)
            self.model.config.save_pretrained(local_model)
            # Reuse downloaded weights instead of storing a second 600 MB copy.
            repo_cache = Path(os.environ["HF_HOME"]) / "hub" / ("models--" + MODEL_ID.replace("/", "--"))
            weights = sorted(repo_cache.glob("snapshots/*/model.safetensors"), key=lambda p: p.stat().st_mtime)
            if not weights:
                raise RuntimeError("Downloaded weights were not found in the model cache.")
            target = local_model / "model.safetensors"
            target.symlink_to(os.path.relpath(weights[-1], local_model))
        self.model = self.model.to(self.device)
        prompts = [template.format(ALIASES.get(name, name))
                   for name in self.labels + BACKGROUND for template in TEMPLATES]
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(prompts), 48):
                tokens = self.processor(text=prompts[start:start + 48], return_tensors="pt", padding=True, truncation=True).to(self.device)
                features = self.model.get_text_features(**tokens)
                chunks.append(features / features.norm(dim=-1, keepdim=True))
            features = torch.cat(chunks).reshape(-1, len(TEMPLATES), chunks[0].shape[-1]).mean(dim=1)
            self.text_features = features / features.norm(dim=-1, keepdim=True)
        self.alternatives = []

    def predict(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.std() < 3:
            self.alternatives = []
            return "Image has too little detail", 0.0
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            features = self.model.get_image_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
            similarities = (features @ self.text_features.T)[0]
            scores = (similarities * self.model.logit_scale.exp()).softmax(dim=0)
            values, indices = scores.topk(3)
        index = int(indices[0])
        score = float(values[0])
        margin = float(similarities[index] - similarities[int(indices[1])])
        self.alternatives = [(self.labels[int(i)], float(v)) for i, v in zip(indices, values) if int(i) < len(self.labels)]
        # Demo heuristics, not calibrated probabilities of correctness.
        if index >= len(self.labels):
            label = "No trash item detected"
        elif float(similarities[index]) < 0.22:
            label = "Unsure - show another angle"
        elif margin < 0.012:
            runner_up = int(indices[1])
            family = common_family(self.labels[index], self.labels[runner_up]) if runner_up < len(self.labels) else None
            family_score = float(scores[[i for i, name in enumerate(self.labels) if name in FAMILIES[family]]].sum()) if family else 0.0
            if family_score >= 0.5:
                label, score = family, family_score
            else:
                label = "Unsure - show another angle"
        else:
            label = self.labels[index]
        return label, score


def center_box(frame):
    height, width = frame.shape[:2]
    size = int(min(height, width) * 0.8)
    return (width - size) // 2, (height - size) // 2, size


def render(frame, label, score, alternatives=()):
    x, y, size = center_box(frame)
    preview = frame.copy()
    cv2.rectangle(preview, (x, y), (x + size, y + size), (80, 255, 120), 2)
    width = 800
    preview = cv2.resize(preview, (width, round(frame.shape[0] * width / frame.shape[1])))
    banner = np.full((180, width, 3), 30, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    title = f"Detected: {label}"
    text_width = cv2.getTextSize(title, font, 1, 2)[0][0]
    scale = min(1.0, (width - 40) / max(text_width, 1))
    cv2.putText(banner, title, (20, 40), font, scale, (80, 255, 120), 2, cv2.LINE_AA)
    detail = "Starting recognition..." if score is None else f"Relative match: {score:.0%} (not certainty)"
    cv2.putText(banner, detail, (20, 80), font, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    if alternatives:
        candidates = "Candidates: " + " / ".join(name for name, _ in alternatives[:3])
        candidate_width = cv2.getTextSize(candidates, font, 0.55, 1)[0][0]
        candidate_scale = min(0.55, 0.55 * (width - 40) / max(candidate_width, 1))
        cv2.putText(banner, candidates, (20, 115), font, candidate_scale, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(banner, "Hold ONE item inside the box | Q to quit", (20, 153), font, 0.65, (200, 200, 200), 1, cv2.LINE_AA)
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
        stable = StablePrediction()
        alternatives = []
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
                    alternatives = list(classifier.alternatives)
                    label = stable.update(label)
                    future = None
                if future is None and time.monotonic() - last_prediction >= 0.35:
                    x, y, size = center_box(frame)
                    future = worker.submit(classifier.predict, frame[y:y + size, x:x + size].copy())
                    last_prediction = time.monotonic()
                cv2.imshow(window, render(frame, label, score, alternatives))
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
    except ImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Use your Miniconda Python: python classifier.py. Install dependencies with python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if isinstance(exc, TimeoutError) or "os error 60" in str(exc).lower() or getattr(exc, "errno", None) == 60:
            print(
                "File access timed out. This is not a missing dependency. "
                "This project is in a Box-synced folder; make the entire Pyth folder "
                "available offline in Box and wait for its files (including .model-cache) "
                "to download, then retry. A local folder outside Box avoids these sync delays.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
