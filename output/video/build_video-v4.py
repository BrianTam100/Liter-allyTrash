from pathlib import Path
import subprocess, wave, json
import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/video'; A=OUT/'assets'; A.mkdir(exist_ok=True)
W,H=1920,1080
BG='#10191d'; WHITE='#eff7f4'; GREEN='#a2efb6'; MUTED='#a3b8b6'
def font(n,bold=False): return ImageFont.truetype('C:/Windows/Fonts/'+('segoeuib.ttf' if bold else 'segoeui.ttf'),n)
def run(args): subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True)
def base(k,tag,title,lines,layout='side'):
 im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 d.rounded_rectangle((80,80,425,130),25,fill=GREEN);d.text((102,87),'LITTER-ALLY TRASH',font=font(26,True),fill=BG)
 d.text((80,195),tag.upper(),font=font(25,True),fill=GREEN)
 if layout=='side':
  y=265
  for line in title.split('\n'): d.text((76,y),line,font=font(88,True),fill=WHITE);y+=108
  y+=38
  for line in lines: d.text((80,y),line,font=font(34),fill=MUTED);y+=52
 else:
  d.text((78,234),title,font=font(64,True),fill=WHITE)
  d.text((80,320),'  /  '.join(lines),font=font(30),fill=MUTED)
 d.line((80,985,1840,985),fill='#33464a',width=2)
 d.text((80,1010),'LITTER-ALLY TRASH  |  PROJECT DEMO',font=font(23,True),fill=MUTED)
 d.text((1740,1005),f'{k:02d} / 08',font=font(25),fill=GREEN)
 return im
def photo(im,name,box):
 p=ImageOps.exif_transpose(Image.open(ROOT/'Media'/name)).convert('RGB')
 im.paste(ImageOps.fit(p,(box[2]-box[0],box[3]-box[1])),box[:2])
def encode_still(k,im,seconds):
 p=A/f'card-{k}.png';im.save(p)
 run(['-loop','1','-i',p,'-t',seconds,'-vf',f"scale=2016:1134,crop=1920:1080:x='48+18*sin(t/3)':y=27,fade=t=in:st=0:d=0.25,fade=t=out:st={seconds-.25}:d=0.25",'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-an',A/f'seg-{k}.mp4'])
def encode_clip(k,im,src,start,seconds,box):
 p=A/f'card-{k}.png';im.save(p);x,y,w,h=box
 vf=f'[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x10191d,setsar=1[v];[1:v][v]overlay={x}:{y}:shortest=1,fade=t=in:st=0:d=0.25,fade=t=out:st={seconds-.25}:d=0.25[out]'
 run(['-ss',start,'-i',ROOT/'Media'/src,'-loop','1','-i',p,'-filter_complex',vf,'-map','[out]','-t',seconds,'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-an',A/f'seg-{k}.mp4'])

def site_card(k,tag,title,lines,name,crop,seconds,note):
 im=base(k,tag,title,lines,'wide')
 p=Image.open(A/name).convert('RGB').crop(crop);p=ImageOps.contain(p,(1760,540))
 im.paste(p,((W-p.width)//2,395));d=ImageDraw.Draw(im)
 d.text((80,948),note,font=font(22),fill=GREEN)
 encode_still(k,im,seconds);print(f'{k}/9 {tag}',flush=True)

def result_frame(k,name,title,caption):
 im=Image.open(A/name).convert('RGB').crop((438,315,1760,1080)).resize((W,H),Image.Resampling.LANCZOS)
 d=ImageDraw.Draw(im);d.rectangle((0,0,W,95),fill=BG);d.text((38,20),'LITTER-ALLY TRASH',font=font(32,True),fill=GREEN);d.text((660,18),title,font=font(40,True),fill=WHITE)
 d.rectangle((0,982,W,H),fill=BG);d.text((38,1008),caption,font=font(30),fill=WHITE);d.text((1740,1010),f'{k:02d} / 08',font=font(25),fill=GREEN)
 return im

def result_clip(k,start,seconds,name,title,caption):
 overlay=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(overlay)
 d.rectangle((0,0,W,95),fill=BG);d.text((38,20),'LITTER-ALLY TRASH',font=font(32,True),fill=GREEN);d.text((660,18),title,font=font(40,True),fill=WHITE)
 d.rectangle((0,982,W,H),fill=BG);d.text((38,1008),caption,font=font(30),fill=WHITE);d.text((1740,1010),f'{k:02d} / 08',font=font(25),fill=GREEN)
 path=A/f'overlay-{k}.png';overlay.save(path)
 vf=f'[0:v]crop=1322:764:438:316,scale=1920:1080,setsar=1[v];[v][1:v]overlay=0:0:shortest=1,fade=t=in:st=0:d=0.2,fade=t=out:st={seconds-.2}:d=0.2[out]'
 run(['-ss',start,'-i',ROOT/'Media/more video.mp4','-loop','1','-i',path,'-filter_complex',vf,'-map','[out]','-t',seconds,'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-an',A/f'seg-{k}.mp4'])
 print(f'{k}/11 {title}',flush=True)

def paired_demo():
 im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 d.text((35,24),'LITTER-ALLY TRASH',font=font(36,True),fill=GREEN)
 d.text((35,91),'WEBSITE: LOCAL AI & BIN RESULT',font=font(25,True),fill=WHITE)
 d.text((1400,91),'OUTSIDE VIEW',font=font(25,True),fill=WHITE)
 d.text((35,1003),'Camera -> Local AI -> Trash or recycling -> Matching lid',font=font(32,True),fill=WHITE)
 d.text((1760,1010),'03 / 08',font=font(25),fill=GREEN)
 path=A/'paired-background.png';im.save(path)
 vf='[0:v]crop=1322:964:438:110,scale=1320:852:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1320:852:(ow-iw)/2:(oh-ih)/2:color=0x10191d,setsar=1,setpts=PTS-STARTPTS[screen];[1:v]scale=480:852:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=480:852:(ow-iw)/2:(oh-ih)/2:color=0x10191d,setsar=1,setpts=PTS-STARTPTS[outside];[2:v][screen]overlay=30:130:shortest=1[bg];[bg][outside]overlay=1400:130:shortest=1,fade=t=in:st=0:d=0.25,fade=t=out:st=21.75:d=0.25[out]'
 run(['-ss','154','-i',ROOT/'Media/more video.mp4','-ss','19','-i',ROOT/'Media/more video Outsider Perspective.MOV','-loop','1','-i',path,'-filter_complex',vf,'-map','[out]','-t','22','-r','30','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-an',A/'seg-3.mp4'])
 print('3/8 synchronized website + outside',flush=True)

im=base(1,'Litter-ally Trash','Show it.\nSort it.',['Local AI identifies the item.','The matching bin lid opens.']);photo(im,'IMG_2706.jpg',(1050,55,1840,950));encode_still(1,im,5);print('1/8 intro',flush=True)
im=base(2,'Local AI model','What are you\nholding?',['Camera frames go to a local','CLIP vision model on the laptop.','It identifies the object and','assigns trash or recycling.']);photo(im,'IMG_3595.jpg',(1050,55,1840,950));encode_still(2,im,7);print('2/8 local AI',flush=True)
paired_demo()
im=base(4,'Automatic lid selection','Recognition chooses the bin.',['Camera image','Local AI detection','Corresponding lid opens'],'wide');d=ImageDraw.Draw(im)
for y,heading,items in [(430,'RECYCLING','Plastic water bottle  /  Cardboard'),(680,'TRASH','Chip bag  /  Paper towel')]:
 d.rounded_rectangle((80,y,1840,y+210),25,fill='#1e3032');d.text((115,y+26),heading,font=font(34,True),fill=GREEN);d.text((115,y+95),items,font=font(40),fill=WHITE);d.text((1220,y+100),'Matching lid opens',font=font(35,True),fill=GREEN)
encode_still(4,im,7);print('4/8 lid routing',flush=True)
site_card(5,'Detection log','See what the AI recognized.',['Totals','Trash vs. recycling','Breakdown by item'],'log-site.png',(365,35,1800,710),8,'Actual detection-log interface with example records.')
site_card(6,'Detection history','Every detection has a record.',['Item','Assigned bin','Match score','Camera source','Time'],'log-site.png',(365,1080,1800,1495),8,'Example records shown. Match score is a relative match, not certainty.')
im=base(7,'Rover controls','Drive it from the website.',['Keyboard & touch','Voice controls','Hand gestures'],'wide');encode_clip(7,im,'theRecording.mp4',19,8,(80,380,1760,580));print('7/8 controls',flush=True)
im=base(8,'Litter-ally Trash','Litter-ally\nTrash.',['Local recognition.','Automatic bin selection.','A dashboard that tracks it.']);photo(im,'IMG_3596.jpg',(1050,55,1840,950));encode_still(8,im,5);print('8/8 ending',flush=True)

# Original 112 BPM electronic instrumental, synthesized from scratch.
sr=48000;dur=70;n=sr*dur;music=np.zeros(n,dtype=np.float64);rng=np.random.default_rng(20261004)
def add(at,sound,gain=1):
 i=int(at*sr);end=min(n,i+len(sound))
 if i<n: music[i:end]+=sound[:end-i]*gain
def tone(freq,length):
 t=np.arange(int(length*sr))/sr;env=(1-np.exp(-t*40))*np.exp(-t*2.5)
 return (np.sin(2*np.pi*freq*t)+.18*np.sin(2*np.pi*2*freq*t))*env
beat=60/112
chords=[[130.81,164.81,196],[110,130.81,164.81],[87.31,110,130.81],[98,123.47,146.83]]
for bar in range(34):
 at=bar*4*beat;notes=chords[(bar//2)%4]
 for f in notes:add(at,tone(f,4*beat),.035)
 for b in range(4):
  t=np.arange(int(.3*sr))/sr;k=np.sin(2*np.pi*(48*t+85*.025*(1-np.exp(-t/.025))))*np.exp(-t*17);add(at+b*beat,k,.2)
  add(at+b*beat,tone(notes[0]/2,.35),.09)
  if b%2:
   t=np.arange(int(.16*sr))/sr;noise=rng.normal(0,1,len(t));add(at+b*beat,noise*np.exp(-t*32),.045)
 for b in range(8):
  t=np.arange(int(.07*sr))/sr;noise=rng.normal(0,1,len(t));noise=np.diff(noise,prepend=0);add(at+b*beat/2,noise*np.exp(-t*70),.014)
  add(at+b*beat/2,tone(notes[b%3]*4,.24),.035)
music=np.tanh(music*1.25);fade=np.minimum(np.arange(n)/(sr*1.5),1)*np.minimum((n-np.arange(n))/(sr*3),1);music*=fade
stereo=np.stack([music,np.roll(music,240)*.97],axis=1);stereo=np.clip(stereo,-1,1)
with wave.open(str(OUT/'original-instrumental.wav'),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes((stereo*32767).astype('<i2').tobytes())
lst=A/'segments.txt';lst.write_text('\n'.join("file 'seg-%d.mp4'"%i for i in range(1,9)))
run(['-f','concat','-safe','0','-i',lst,'-i',OUT/'original-instrumental.wav','-map','0:v:0','-map','1:a:0','-c:v','copy','-af','loudnorm=I=-18:TP=-2:LRA=7','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',OUT/'Litter-ally-Trash-YouTube.mp4'])
(OUT/'README.txt').write_text('Litter-ally Trash project video\n70 seconds / 1920 x 1080 / 30 fps / H.264 + AAC\n\nPaired demo: Media/more video.mp4 154-176 seconds and Media/more video Outsider Perspective.MOV 19-41 seconds, at original speed. The full requested website interval 162-175 seconds is included. Synchronization offset: website 166 seconds = outside 31 seconds (bottle recognition). The extra website lead-in and tail cover the complete outside interval. The previous IMG_3593.MOV live-test footage is removed. Detection log uses real app screenshots with explicitly labeled example records.\nMusic is an original synthesized instrumental with no third-party samples.\nRebuild: BRH_Test/.venv/Scripts/python.exe output/video/build_video.py\n')
print('DONE',flush=True)
