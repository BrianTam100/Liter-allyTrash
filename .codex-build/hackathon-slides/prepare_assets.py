from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
DEST = Path(__file__).resolve().parent / 'assets'
def save(name, source, crop=None):
    image = ImageOps.exif_transpose(Image.open(ROOT / source)).convert('RGB')
    if crop: image = image.crop(crop)
    image.save(DEST / name)

save('cover.jpg', 'Media/IMG_3596.jpg', (110, 180, 2050, 2430))
save('architecture.jpg', 'Media/IMG_3597.jpg', (320, 210, 1760, 2250))
save('lids.jpg', 'Media/IMG_3595.jpg', (90, 250, 2070, 2170))
save('scanner.png', 'output/video/assets/real-bottle-visible.png', (438, 398, 1760, 904))
save('gestures.png', 'Media/HandGuestureProof.png', (0, 70, 1160, 1330))
save('log.png', 'output/video/assets/live-log-site.png', (368, 1008, 1800, 1428))
save('gemini.png', 'Media/Gemini-Integration.png', (1690, 434, 2770, 1502))
save('brand.png', 'output/video/assets/card-17.png', (80, 80, 426, 131))
