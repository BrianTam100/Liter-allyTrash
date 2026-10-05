"""Keep exactly source seconds 0-25 of the inserted stool demonstration."""
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
source = HERE / 'Litter-ally-Trash-YouTube-Final-Bottle-Fix.mp4'
result = HERE / 'Litter-ally-Trash-YouTube-Final-25s-Demo.mp4'
# Insert starts at 131.3; remove the original clip's final 6.1 seconds.
graph = (
    '[0:v]split=2[pv][qv];'
    '[pv]trim=end=156.3,setpts=PTS-STARTPTS[v0];'
    '[qv]trim=start=162.4:end=172.5,setpts=PTS-STARTPTS[v1];'
    '[0:a]asplit=2[pa][qa];'
    '[pa]atrim=end=156.3,asetpts=PTS-STARTPTS,'
    'afade=t=out:st=156.15:d=0.15[a0];'
    '[qa]atrim=start=162.4:end=172.5,asetpts=PTS-STARTPTS[a1];'
    '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]'
)
subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y',
    '-i', str(source), '-filter_complex', graph, '-map', '[v]', '-map', '[a]',
    '-r', '30', '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
    '-profile:v', 'high', '-level:v', '4.1', '-g', '60', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-ar', '48000', '-b:a', '192k', '-movflags', '+faststart',
    str(result)], check=True)
chapters = (HERE / 'chapters-with-real-world-demo.txt').read_text()
(HERE / 'chapters-final-25s-demo.txt').write_text(
    chapters.replace('2:42 Gemini', '2:36 Gemini').replace('2:48 Recognize', '2:42 Recognize'))
print(result, flush=True)
