"""Recognize one common trash item at a time using pretrained CLIP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HOME", str(ROOT / ".model-cache"))

import cv2
import numpy as np

# The large model recognizes items noticeably better; set TRASH_MODEL to
# openai/clip-vit-base-patch16 for the smaller, faster one on slow machines.
MODEL_ID = os.environ.get("TRASH_MODEL", "openai/clip-vit-large-patch14")
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
    "paper towel": "a crumpled used paper towel",
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

# Everyday names shown to people; the model keeps the descriptive labels above.
DISPLAY_NAMES = {
    "plastic soda bottle": "soda bottle",
    "plastic milk jug": "milk jug", "plastic yogurt cup": "yogurt cup",
    "plastic food container": "food container", "plastic grocery bag": "plastic bag",
    "plastic cup lid": "cup lid", "plastic bottle cap": "bottle cap",
    "aluminum soda can": "soda can", "steel food can": "food can",
    "aluminum food tray": "foil tray", "metal jar lid": "jar lid",
    "cardboard tube": "toilet paper roll", "sheet of paper": "paper",
    "paper envelope": "envelope", "paper coffee cup": "coffee cup", "used tissue": "tissue",
    "potato chip bag": "chip bag", "snack bar wrapper": "granola bar wrapper",
    "styrofoam food container": "styrofoam container", "broken headphones": "headphones",
    "old shoe": "shoe", "plastic takeout lid": "takeout lid",
    "plastic clamshell packaging": "clamshell container", "plastic squeeze bottle": "squeeze bottle",
    "plastic spray bottle": "spray bottle", "plastic ketchup bottle": "ketchup bottle",
    "plastic mustard bottle": "mustard bottle", "plastic dish soap bottle": "dish soap bottle",
    "plastic hand soap bottle": "hand soap bottle", "plastic lotion bottle": "lotion bottle",
    "plastic medicine bottle": "pill bottle", "plastic pill blister pack": "blister pack",
    "plastic toothbrush packaging": "toothbrush packaging", "plastic zip tie": "zip tie",
    "plastic bread bag clip": "bread clip", "plastic clothes hanger": "clothes hanger",
    "plastic plant pot": "plant pot", "plastic bucket": "bucket",
    "plastic packaging strap": "packing strap", "plastic six pack rings": "six-pack rings",
    "plastic mesh produce bag": "mesh produce bag", "plastic freezer bag": "freezer bag",
    "plastic sandwich bag": "sandwich bag", "plastic trash bag": "trash bag",
    "plastic toy": "toy", "plastic ruler": "ruler", "plastic comb": "comb",
    "plastic hairbrush": "hairbrush", "plastic razor": "razor",
    "plastic deodorant stick": "deodorant", "tooth floss container": "floss container",
    "empty bandage wrapper": "bandage wrapper", "adhesive bandage": "bandage",
    "foil coffee bag": "coffee bag", "coffee capsule": "coffee pod",
    "instant noodle packet": "noodle packet", "instant noodle cup": "cup noodles",
    "sauce sachet": "sauce packet", "paper ice cream cup": "ice cream cup",
    "paper straw wrapper": "straw wrapper", "wooden chopsticks": "chopsticks",
    "wooden stir stick": "stir stick", "wooden toothpick": "toothpick",
    "wooden popsicle stick": "popsicle stick", "marker pen": "marker",
    "adhesive tape roll": "tape", "metal screw": "screw", "metal nail": "nail",
    "metal washer": "washer", "metal nut": "nut", "metal bolt": "bolt", "metal key": "key",
    "metal bottle cap": "bottle cap", "can pull tab": "can tab", "foil yogurt lid": "yogurt lid",
    "metal cookie tin": "cookie tin", "metal tea tin": "tea tin",
    "empty aerosol can": "aerosol can", "aluminum tube": "metal tube",
    "disposable baking tray": "foil baking tray", "glass drinking cup": "drinking glass",
    "broken ceramic": "broken ceramics", "glass condiment bottle": "condiment bottle",
    "glass sauce jar": "sauce jar", "glass jam jar": "jam jar", "glass candle jar": "candle jar",
    "cardboard drink carrier": "drink carrier", "cardboard shipping mailer": "shipping mailer",
    "cardboard food sleeve": "cardboard sleeve", "cardboard tissue box": "tissue box",
    "cardboard shoe box": "shoe box", "paper business card": "business card",
    "paper ticket": "ticket", "paper label": "label", "paper confetti": "confetti",
    "paper baking liner": "cupcake liner", "paper doily": "doily",
    "wristwatch strap": "watch strap", "9 volt battery": "9V battery", "CD disc": "CD",
    "plant leaves": "leaves", "small twig": "twig", "electrical cable": "cable",
}


def display_name(label):
    return DISPLAY_NAMES.get(label, label)


TRASH_ITEMS = set(json.loads((ROOT / "trash_items.json").read_text()))
# Items not listed in recyclable_items.json are trash. Drop-off items are
# recyclable, but not in the curbside bin (batteries, electronics, film).
_recyclable = json.loads((ROOT / "recyclable_items.json").read_text())
DROP_OFF = set(_recyclable["drop_off"])
RECYCLABLE = set(_recyclable["curbside"]) | DROP_OFF


# The only items the detector reports, and which lid each opens. Each lists the
# model labels that count as it. Every other label in trash_items.json is still
# compared so other objects are recognized as "not a sorted item" instead of being
# forced into one of these.
TARGETS = {
    "plastic water bottle": ("Recyclable", {"plastic water bottle"}),
    "cardboard": ("Recyclable", {"cardboard box", "pizza box", "cereal box", "cardboard tube",
                                 "cardboard shipping mailer", "cardboard tissue box", "cardboard shoe box",
                                 "cardboard drink carrier", "cardboard food sleeve"}),
    "paper towel": ("Trash", {"paper towel", "paper napkin"}),
    "chip bag": ("Trash", {"potato chip bag"}),
}
NOT_SORTED = "No sorted item detected"


def category(item):
    """Return "Recyclable" or "Trash" for a target item, or None for anything else."""
    return TARGETS[item][0] if item in TARGETS else None


def common_family(first, second):
    return next((name for name, members in FAMILIES.items() if first in members and second in members), None)


def cache_weights(source, target):
    """Reuse downloaded weights, including on Windows without symlink privileges."""
    try:
        target.symlink_to(os.path.relpath(source, target.parent))
    except OSError:
        try:
            os.link(source.resolve(), target)
        except OSError:
            shutil.copyfile(source, target)


class StablePrediction:
    """Require two successive accepted readings; clear old labels immediately."""
    def __init__(self):
        self.pending = None
        self.count = 0

    def update(self, label):
        if label.startswith(("No ", "Hold", "Image")):
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
        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        name = "model-patch16" if MODEL_ID == "openai/clip-vit-base-patch16" else MODEL_ID.split("/")[-1]
        local_model = ROOT / ".model-cache" / ("ready-" + name)
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
            cache_weights(weights[-1], target)
        # Half precision roughly halves GPU inference time with no visible change in scores.
        self.model = self.model.to(self.device, torch.float16 if self.device == "cuda" else torch.float32)
        prompts = [template.format(ALIASES.get(name, name))
                   for name in self.labels + BACKGROUND for template in TEMPLATES]
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(prompts), 48):
                tokens = self.processor(text=prompts[start:start + 48], return_tensors="pt", padding=True, truncation=True).to(self.device)
                features = self.model.get_text_features(**tokens).float()
                chunks.append(features / features.norm(dim=-1, keepdim=True))
            features = torch.cat(chunks).reshape(-1, len(TEMPLATES), chunks[0].shape[-1]).mean(dim=1)
            self.text_features = features / features.norm(dim=-1, keepdim=True)
        missing = set().union(*(members for _, members in TARGETS.values())) - set(self.labels)
        if missing:
            raise ValueError(f"TARGETS lists labels missing from trash_items.json: {sorted(missing)}")
        self.target_members = {name: [i for i, label in enumerate(self.labels) if label in members]
                               for name, (_, members) in TARGETS.items()}
        self.alternatives = []
        self.category = None

    def predict(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.std() < 3:
            self.alternatives = []
            self.category = None
            return "Image has too little detail", 0.0
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Pad the detection rectangle to a square so CLIP's center crop keeps its edges.
        height, width = rgb.shape[:2]
        if height != width:
            side = max(height, width)
            top, left = (side - height) // 2, (side - width) // 2
            rgb = cv2.copyMakeBorder(rgb, top, side - height - top, left, side - width - left,
                                     cv2.BORDER_CONSTANT, value=(128, 128, 128))
        # Average the frame with its mirror image for a steadier match.
        inputs = self.processor(images=[rgb, np.ascontiguousarray(rgb[:, ::-1])], return_tensors="pt").to(self.device, self.model.dtype)
        with self.torch.inference_mode():
            features = self.model.get_image_features(**inputs).float()
            features = features / features.norm(dim=-1, keepdim=True)
            features = features.mean(dim=0, keepdim=True)
            features = features / features.norm(dim=-1, keepdim=True)
            similarities = (features @ self.text_features.T)[0]
            scores = (similarities * self.model.logit_scale.exp()).softmax(dim=0)
        index = int(scores.argmax())
        # Only the target items are reported; each target's score sums its labels.
        totals = {name: float(scores[members].sum()) for name, members in self.target_members.items()}
        self.alternatives = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:3]
        target = next((name for name, members in self.target_members.items() if index in members), None)
        self.category = category(target)
        if target is None:
            label, score = NOT_SORTED, float(scores[index])
        else:
            label, score = target, totals[target]
        return label, score


BOX_FRACTION = 1.0  # Detect across the entire camera frame.


def center_box(frame):
    height, width = frame.shape[:2]
    box_width, box_height = int(width * BOX_FRACTION), int(height * BOX_FRACTION)
    return (width - box_width) // 2, (height - box_height) // 2, box_width, box_height


def render(frame, label, score, alternatives=(), bin_name=None):
    x, y, box_width, box_height = center_box(frame)
    preview = frame.copy()
    cv2.rectangle(preview, (x, y), (x + box_width - 1, y + box_height - 1), (80, 255, 120), 2)
    width = 800
    preview = cv2.resize(preview, (width, round(frame.shape[0] * width / frame.shape[1])))
    banner = np.full((180, width, 3), 30, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    title = f"{bin_name}: {label}" if bin_name else f"Detected: {label}"
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
        bin_name = None
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
                    bin_name = None if label.startswith("Hold") else classifier.category
                    future = None
                if future is None and time.monotonic() - last_prediction >= 0.35:
                    x, y, box_width, box_height = center_box(frame)
                    future = worker.submit(classifier.predict, frame[y:y + box_height, x:x + box_width].copy())
                    last_prediction = time.monotonic()
                cv2.imshow(window, render(frame, label, score, alternatives, bin_name))
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
            print(f"{classifier.category or 'Detected'}: {label} | Relative match: {score:.0%} (not certainty)")
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
