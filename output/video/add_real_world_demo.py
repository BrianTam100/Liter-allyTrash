"""Add the new real-world demo to the approved repaired cut without changing its scenes."""
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Reuse only the drawing helpers, not the original build's rendering commands.
helpers = (HERE / 'build_video.py').read_text().split("im=base(1,")[0]
exec(compile(helpers, str(HERE / 'build_video.py'), 'exec'))

original = HERE / 'Litter-ally-Trash-YouTube-Repaired.mp4'
source = ROOT / 'Media/howToWorkThisIn.MOV'
insert_at = 131.3  # Exact frame boundary after the hand-tracking close-up.
clip_duration = 31.1
original_duration = 141.4
result = HERE / 'Litter-ally-Trash-YouTube-With-Real-World-Demo.mp4'

card = base(18, 'Real-world demonstration', 'All together.\nIn action.',
            ['Drive the rover closer.', 'Show the item.', 'Watch the lid respond.'])
ImageDraw.Draw(card).text((80, 920), 'Original demo audio', font=font(26), fill=GREEN)
card_path = A / 'card-18-real-world.png'
card.save(card_path)

# The iPhone source is HLG HDR. Convert to SDR before combining it with the cut.
tone = ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,'
        'tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,'
        'format=yuv420p')
segment = A / 'seg-18-real-world.mp4'
run(['-i', source, '-loop', '1', '-i', card_path,
     '-filter_complex',
     f'[0:v]{tone},fps=30,scale=540:960,setsar=1,setpts=PTS-STARTPTS[v];'
     '[1:v]fps=30[card];[card][v]overlay=1200:55:shortest=1,'
     'fade=t=in:st=0:d=0.25,fade=t=out:st=30.85:d=0.25[out];'
     '[0:a]atrim=duration=31.1,asetpts=PTS-STARTPTS,'
     'loudnorm=I=-18:TP=-2:LRA=7,aresample=48000,'
     'afade=t=in:st=0:d=0.12,afade=t=out:st=30.95:d=0.15[a]',
     '-map', '[out]', '-map', '[a]', '-t', clip_duration, '-r', '30',
     '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
     '-profile:v', 'high', '-level:v', '4.1', '-pix_fmt', 'yuv420p',
     '-c:a', 'aac', '-ar', '48000', '-b:a', '192k', segment])
print('New demo segment ready', flush=True)

# Preserve the approved video's picture and mixed audio, including its voice cue.
# Only add a gentle music fade around the inserted clip's original audio.
graph = (
    '[0:v]split=2[pv][qv];'
    '[pv]trim=end=131.3,setpts=PTS-STARTPTS[v0];'
    '[qv]trim=start=131.3:end=141.4,setpts=PTS-STARTPTS[v2];'
    '[1:v]trim=duration=31.1,setpts=PTS-STARTPTS[v1];'
    '[0:a]apad,asplit=2[pa][qa];'
    '[pa]atrim=end=131.3,asetpts=PTS-STARTPTS,'
    'afade=t=out:st=128.3:d=3[a0];'
    '[qa]atrim=start=131.3:end=141.4,asetpts=PTS-STARTPTS,'
    'afade=t=in:st=0:d=1.5[a2];'
    '[1:a]apad,atrim=duration=31.1,asetpts=PTS-STARTPTS[a1];'
    '[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]'
)
run(['-i', original, '-i', segment, '-filter_complex', graph,
     '-map', '[v]', '-map', '[a]', '-r', '30',
     '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
     '-profile:v', 'high', '-level:v', '4.1', '-g', '60',
     '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000',
     '-b:a', '192k', '-movflags', '+faststart', '-map_metadata', '-1', result])

(HERE / 'chapters-with-real-world-demo.txt').write_text(
    '0:00 Litter-ally Trash\n0:07 The hardware\n0:14 Rover movement\n'
    '0:34 Local AI recognition\n0:40 Website and outside view\n'
    '1:02 Recycling result\n1:05 Trash result\n1:08 Automatic lid selection\n'
    '1:12 Every detection has a record\n1:18 Shared data in TigerData\n'
    '1:25 Website controls\n1:34 Voice control\n1:55 Hand gestures\n'
    '2:08 Hand-tracking close-up\n2:11 Real-world demonstration\n'
    '2:42 Gemini Sort Guide\n2:48 Recognize. Sort. Connect.\n')
print(result, flush=True)
