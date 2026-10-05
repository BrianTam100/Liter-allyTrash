"""Replace only the bottle-result still at 1:02-1:05 in the latest edit."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
exec(compile((HERE / 'build_video.py').read_text().split("im=base(1,")[0],
             str(HERE / 'build_video.py'), 'exec'))
image = result_frame(6, 'real-bottle-visible.png', 'Bottle -> RECYCLING',
                     'Local model recognizes a plastic water bottle and selects the recycling bin.')
card = A / 'card-6-bottle-visible.png'
image.save(card)
source = HERE / 'Litter-ally-Trash-YouTube-With-Real-World-Demo.mp4'
result = HERE / 'Litter-ally-Trash-YouTube-Final-Bottle-Fix.mp4'
run(['-i', source, '-loop', '1', '-framerate', '30', '-i', card,
     '-filter_complex',
     "[1:v]fade=t=in:st=62:d=0.25,fade=t=out:st=64.75:d=0.25[still];"
     "[0:v][still]overlay=0:0:enable='gte(t,62)*lt(t,65)':shortest=1[v]",
     '-map', '[v]', '-map', '0:a:0', '-t', '172.5', '-r', '30',
     '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
     '-profile:v', 'high', '-level:v', '4.1', '-g', '60',
     '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', result])
print(result, flush=True)
