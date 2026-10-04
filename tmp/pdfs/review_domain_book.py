from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

folder = Path(__file__).resolve().parent
images = sorted(folder.glob('preview-*.png'))
assert len(images) == 100, len(images)
font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 14)
for sheet_index in range(5):
    sheet = Image.new('RGB', (1200, 1630), '#e4e6e5')
    draw = ImageDraw.Draw(sheet)
    for slot, path in enumerate(images[sheet_index * 20:(sheet_index + 1) * 20]):
        with Image.open(path) as image:
            image.thumbnail((280, 363))
            x = (slot % 4) * 300 + 10
            y = (slot // 4) * 326 + 22
            # A modest thumbnail keeps all twenty pages visible on one sheet.
            image.thumbnail((226, 293))
            sheet.paste(image, (x + 26, y))
        draw.text((x + 26, y - 18), f'Page {sheet_index * 20 + slot + 1:03d}', font=font, fill='#26343c')
    sheet.save(folder / f'contact-{sheet_index+1}.png')
print('Rendered all 100 pages; created five review sheets.')
