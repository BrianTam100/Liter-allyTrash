from pathlib import Path
from collections import Counter
import csv
import json
import re
import math
from html import escape

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
TMP = ROOT / 'tmp' / 'pdfs'

for name, filename in [('Body', 'segoeui.ttf'), ('Bold', 'segoeuib.ttf'), ('Light', 'segoeuil.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / filename)))

pages = []
group = None
for line in (TMP / 'domain_pages.txt').read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    if '|' not in line:
        group = line.strip()
        continue
    title, description, raw_names = line.split('|')
    pages.append(dict(group=group, title=title, description=description, raw_names=raw_names.split()))

assert len(pages) == 100
assert all(len(page['raw_names']) == 10 for page in pages)
domains = [domain.lower() for page in pages for domain in page['raw_names']]
assert len(domains) == len(set(domains)) == 1000
roots = [domain.split('.')[0] for domain in domains]
assert len(roots) == len(set(roots)), 'Repeated root with different TLD'
assert not any('john' in domain for domain in domains)
assert all(re.fullmatch(r'[a-z0-9]+\.(com|dev|net|tech|io)', domain) for domain in domains)
assert all(len(root) <= 63 for root in roots)

INTERESTS = [
    ('Robotics, rovers, and servos', 'SortRover; the servo-control conversation and PCA9685 calibration.'),
    ('Raspberry Pi and embedded computing', 'Pi display, HDMI, SSH, camera, and servo-controller questions.'),
    ('Electronics and hardware tinkering', 'Wiring, servo pulse widths, device connections, and calibration.'),
    ('C++ / Python / web development', 'C++ chats, the game-tooling project, and the Flask/Python dashboard.'),
    ('AI, vision, and image classification', 'The live-classifier conversation and SortRover recognition code.'),
    ('Recycling and sorting automation', 'SortRover and its recycling, bin-control, and points dashboard.'),
    ('Custom watches and wearables', 'The customWatch project; device details were not inspected.'),
    ('Hackathons and practical side projects', 'The three-night hackathon packing conversation and project collection.'),
    ('Servers, memory, and homelabs', 'Dell R740xd memory questions and AI-computer hardware questions.'),
    ('Networking and remote computer control', 'SSH, Tailscale, and GLiNet mobile/KVM interface conversations.'),
    ('Local AI hardware and image generation', 'AI Coding System Cost, including the image-generation question.'),
    ('Gaming tools and overlays', 'BoomBeechInfo and its Boom Beach memory/overlay work.'),
    ('Bots and community software', 'crazycord, whose README describes a member backup/restore service.'),
    ('Calculus, MATLAB, and technical learning', 'Series, derivatives, numerical tools, and practice-test chats; possibly coursework.'),
    ('Creative, playful naming', 'This conversation: requests for creative, unique, fun names without John.'),
]

BASIS = {
    'ROBOTICS & ROVERS': 'SortRover + PCA9685 servo-control and calibration chats.',
    'ELECTRONICS & EMBEDDED': 'Pi displays, wiring, servo control, and device troubleshooting.',
    'CODING & SOFTWARE': 'C++ chats + Python/Flask projects + practical programming work.',
    'AI & COMPUTER VISION': 'SortRover classification + local AI hardware and image-generation questions.',
    'WATCHES & WEARABLES': 'The customWatch project; detailed device preferences are unknown.',
    'HACKATHONS & BUILD CULTURE': 'The three-night hackathon chat + your collection of side projects.',
    'SERVERS & NETWORKS': 'R740xd RAM, SSH, remote access, and mobile KVM questions.',
    'GAMES & COMMUNITY TOOLS': 'BoomBeechInfo game tooling + crazycord community recovery software.',
    'RECYCLING & MATH REMIXES': 'SortRover recycling; calculus/MATLAB appear in study conversations.',
    'CREATIVE CROSSOVERS': 'Imaginative remixes of your projects; these are naming styles, not inferred hobbies.',
}
USES = {
    'ROBOTICS & ROVERS': 'A rover project, robotics build log, or maker identity.',
    'ELECTRONICS & EMBEDDED': 'Hardware experiments, embedded tools, or an electronics studio.',
    'CODING & SOFTWARE': 'A developer portfolio, software tool, or coding journal.',
    'AI & COMPUTER VISION': 'An AI experiment, vision dashboard, or creative software tool.',
    'WATCHES & WEARABLES': 'A wearable project, watch build diary, or compact-device brand.',
    'HACKATHONS & BUILD CULTURE': 'A project collection, hackathon team, or invention blog.',
    'SERVERS & NETWORKS': 'A homelab dashboard, remote-control tool, or systems blog.',
    'GAMES & COMMUNITY TOOLS': 'A game utility, bot project, or community software product.',
    'RECYCLING & MATH REMIXES': 'A sorting project or study tool; each page follows its own theme.',
    'CREATIVE CROSSOVERS': 'A flexible identity that leaves room for your next experiment.',
}
COLORS = ['#176C61', '#A34826', '#4057A8', '#71509F', '#8F4561', '#9C630F', '#276D88', '#6753A0', '#517332', '#985046']
INK = HexColor('#202B37')
MUTED = HexColor('#64717A')
PAPER = HexColor('#FBF9F3')
RULE = HexColor('#DEDCD3')
W, H = 612, 792
LEFT, RIGHT = 44, 568
BOUNDS = []

def text(c, x, top, value, font='Body', size=11, color=INK, align='left'):
    value = str(value)
    width = pdfmetrics.stringWidth(value, font, size)
    left = x if align == 'left' else x - width if align == 'right' else x - width / 2
    assert left >= 0 and left + width <= W, (value, left, width)
    assert 0 < top < H, (value, top)
    BOUNDS.append((c.getPageNumber(), value, left, top, width, size))
    c.setFillColor(color)
    c.setFont(font, size)
    if align == 'right':
        c.drawRightString(x, H - top, value)
    elif align == 'center':
        c.drawCentredString(x, H - top, value)
    else:
        c.drawString(x, H - top, value)

def wrap(value, font, size, width):
    words = value.split()
    lines, current = [], ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if current and pdfmetrics.stringWidth(candidate, font, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines

def paragraph(c, x, top, value, width=524, size=11, leading=15, color=MUTED):
    lines = wrap(value, 'Body', size, width)
    for offset, line in enumerate(lines):
        text(c, x, top + offset * leading, line, size=size, color=color)
    return top + len(lines) * leading

READINGS = {
    'cogmello': 'cog-MEL-oh', 'voltumble': 'volt-UM-bull', 'botterly': 'BOT-er-lee',
    'tickaroo': 'tick-uh-ROO', 'solderoo': 'SOL-der-oo', 'bracketto': 'brack-ET-oh',
    'roveberry': 'ROVE-bear-ee', 'pinoodle': 'pin-OO-dull',
    'byteblossom': 'bite-BLOSS-um', 'tinkletop': 'TINK-ul-top',
}

def concept(value):
    root = value.split('.')[0]
    if root.lower() in READINGS:
        return root + ' / ' + READINGS[root.lower()]
    root = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', root)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', root)

pdf_path = OUT / 'maker_domain_names_100_pages.pdf'
c = canvas.Canvas(str(pdf_path), pagesize=(W, H), pageCompression=1)
c.setTitle('The Maker Domain Book: 1,000 Ideas / 100 Pages')
c.setAuthor('Codex')
c.setSubject('Domain-name brainstorming based on visible project and conversation history')
c.setKeywords('domains, robotics, electronics, coding, watches, hackathons, homelab')
c.showOutline()

for page_number, page in enumerate(pages, 1):
    section_index = (page_number - 1) // 10
    accent = HexColor(COLORS[section_index])
    bookmark = f'theme-{page_number}'
    c.bookmarkPage(bookmark)
    if (page_number - 1) % 10 == 0:
        c.addOutlineEntry(page['group'].title(), bookmark, level=0, closed=False)
    c.addOutlineEntry(f'{page_number:03d} | {page["title"]}', bookmark, level=1, closed=False)
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(accent)
    c.rect(0, H - 7, W, 7, fill=1, stroke=0)
    text(c, LEFT, 33, 'THE MAKER DOMAIN BOOK', font='Bold', size=9, color=accent)
    text(c, RIGHT, 33, f'CHAPTER {section_index + 1:02d} / 10', size=9, color=MUTED, align='right')
    text(c, LEFT, 59, page['group'], size=9, color=MUTED)
    title_size = 30
    while pdfmetrics.stringWidth(page['title'], 'Bold', title_size) > RIGHT - LEFT:
        title_size -= 0.5
    text(c, LEFT, 101, page['title'], font='Bold', size=title_size)
    paragraph(c, LEFT, 128, page['description'], size=11.5, leading=16)

    if page_number == 1:
        text(c, LEFT, 164, 'WHAT YOUR HISTORY POINTS TO', font='Bold', size=9, color=accent)
        for i, (interest, _) in enumerate(INTERESTS[:14]):
            col, row = divmod(i, 7)
            text(c, LEFT + col * 270, 183 + row * 14, interest, size=9.2)
        text(c, LEFT, 287, 'Plus: playful naming. Math may be coursework; the list is an inference.', size=8.4, color=MUTED)
        start, height = 302, 37
    else:
        text(c, LEFT, 170, 'GOOD FOR', font='Bold', size=8.5, color=accent)
        paragraph(c, LEFT, 189, USES[page['group']], size=10.3, leading=14)
        start, height = 218, 44

    for local_index, raw_domain in enumerate(page['raw_names']):
        domain = raw_domain.lower()
        top = start + local_index * height
        global_id = (page_number - 1) * 10 + local_index + 1
        if local_index == 0:
            c.setFillColor(HexColor('#EDE9DC'))
            c.roundRect(LEFT - 8, H - (top + height - 4), RIGHT - LEFT + 16, height - 3, 7, fill=1, stroke=0)
        text(c, LEFT, top + 23, f'{global_id:04d}', size=8.5, color=accent)
        max_width = 392
        domain_size = 20
        while pdfmetrics.stringWidth(domain, 'Bold', domain_size) > max_width:
            domain_size -= 0.25
        text(c, LEFT + 42, top + 24, domain, font='Bold', size=domain_size)
        if local_index == 0:
            text(c, RIGHT - 5, top + 23, 'PICK', font='Bold', size=7.8, color=accent, align='right')
        else:
            c.setStrokeColor(HexColor('#B9B8AF'))
            c.setLineWidth(0.7)
            c.circle(RIGHT - 13, H - (top + 19), 4.0, fill=0, stroke=1)
        if local_index > 0:
            c.setStrokeColor(RULE)
            c.setLineWidth(0.4)
            c.line(LEFT, H - (top + height - 1), RIGHT, H - (top + height - 1))

    text(c, LEFT, 686, 'HISTORY CONNECTION', font='Bold', size=8, color=accent)
    paragraph(c, LEFT, 701, BASIS[page['group']], size=8.5, leading=11)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.7)
    c.line(LEFT, H - 722, RIGHT, H - 722)
    text(c, LEFT, 742, '1,000 distinct ideas. No John names. Availability not checked.', size=8.4, color=MUTED)
    text(c, RIGHT, 742, f'{page_number:03d} / 100', font='Bold', size=10, color=accent, align='right')
    text(c, LEFT, 762, 'Creative suggestions; originality beyond this collection is not verified.', size=8, color=MUTED)
    # Each chapter occupies ten pages. This bar shows progress through the book.
    for block in range(10):
        c.setFillColor(HexColor(COLORS[block]) if block <= section_index else HexColor('#E5E1D7'))
        c.rect(RIGHT - 99 + block * 10, 23, 7, 4, fill=1, stroke=0)
    c.showPage()
c.save()

csv_path = OUT / 'maker_domain_names_searchable.csv'
with csv_path.open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['ID', 'PDF page', 'Chapter', 'Theme', 'Domain', 'Name concept', 'Page pick', 'Theme inspiration'])
    for pn, page in enumerate(pages, 1):
        for index, name in enumerate(page['raw_names']):
            writer.writerow([(pn - 1) * 10 + index + 1, pn, page['group'], page['title'], name.lower(), concept(name), 'Yes' if index == 0 else '', page['description']])

md_path = OUT / 'maker_interests_and_domain_names.md'
with md_path.open('w', encoding='utf-8') as stream:
    stream.write('# Your maker interests and 1,000 domain ideas\n\n')
    stream.write('Based on visible recent chats and project files, not a complete account history. These are inferred interests and recurring topics. A study question may reflect coursework rather than a hobby.\n\n')
    stream.write('## What your history suggests\n\n')
    for interest, source in INTERESTS:
        stream.write(f'- **{interest}:** {source}\n')
    stream.write('\n## Naming direction\n\n')
    stream.write('Creative, playful, and sometimes odd. No domains containing John. Every root is distinct within this collection; no repeats with a different extension. Existing registration, trademark status, and originality outside this list have not been checked. Spaces, nature, food, and animals are creative remixes, not inferred personal hobbies.\n\n')
    stream.write('## Chapter map\n\n')
    for i in range(10):
        stream.write(f'- Pages {i * 10 + 1}-{i * 10 + 10}: {pages[i * 10]["group"].title()}\n')
    for pn, page in enumerate(pages, 1):
        stream.write(f'\n## Page {pn:03d}: {page["title"]}\n\n{page["description"]}\n\n')
        for idx, name in enumerate(page['raw_names']):
            tag = ' - page pick' if idx == 0 else ''
            stream.write(f'{(pn - 1) * 10 + idx + 1}. **{name.lower()}** ({concept(name)}){tag}\n')

reader = PdfReader(pdf_path)
assert len(reader.pages) == 100
for i, page in enumerate(reader.pages):
    extracted = page.extract_text()
    for raw_domain in pages[i]['raw_names']:
        assert raw_domain.lower() in extracted, (i + 1, raw_domain)
    assert f'{i+1:03d} / 100' in extracted
    assert 'Availability not checked' in extracted

# Validate CSV after writing, rather than relying on the source data alone.
with csv_path.open(encoding='utf-8-sig', newline='') as stream:
    rows = list(csv.DictReader(stream))
assert len(rows) == 1000
assert len({row['Domain'] for row in rows}) == 1000
assert sum(row['Page pick'] == 'Yes' for row in rows) == 100

audit = {
    'pages': len(reader.pages), 'domains': len(rows), 'unique_domains': len(set(domains)),
    'unique_roots': len(set(roots)), 'domains_per_page': 10, 'page_picks': 100,
    'first_name_matches': 0, 'availability_checked': False,
    'minimum_domain_font_size': min(item[5] for item in BOUNDS if item[1] in domains),
    'files': [str(pdf_path), str(csv_path), str(md_path)],
}
(TMP / 'audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
print(json.dumps(audit, indent=2))
