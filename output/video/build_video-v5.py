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
 # Clean footer without scene numbers
 return im
def photo(im,name,box):
 p=ImageOps.exif_transpose(Image.open(ROOT/'Media'/name)).convert('RGB')
 im.paste(ImageOps.fit(p,(box[2]-box[0],box[3]-box[1])),box[:2])
def encode_still(k,im,seconds):
 p=A/f'card-{k}.png';im.save(p)
 run(['-loop','1','-i',p,'-t',seconds,'-vf',f"fade=t=in:st=0:d=0.25,fade=t=out:st={seconds-.25}:d=0.25",'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-an',A/f'seg-{k}.mp4'])
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
 d.rectangle((0,982,W,H),fill=BG);d.text((38,1008),caption,font=font(30),fill=WHITE);# No scene numbers
 return im

def result_clip(k,start,seconds,name,title,caption):
 overlay=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(overlay)
 d.rectangle((0,0,W,95),fill=BG);d.text((38,20),'LITTER-ALLY TRASH',font=font(32,True),fill=GREEN);d.text((660,18),title,font=font(40,True),fill=WHITE)
 d.rectangle((0,982,W,H),fill=BG);d.text((38,1008),caption,font=font(30),fill=WHITE);# No scene numbers
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
 # No scene numbers
 path=A/'paired-background.png';im.save(path)
 vf='[0:v]crop=1322:964:438:110,scale=1320:852:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1320:852:(ow-iw)/2:(oh-ih)/2:color=0x10191d,setsar=1,setpts=PTS-STARTPTS[screen];[1:v]scale=480:852:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=480:852:(ow-iw)/2:(oh-ih)/2:color=0x10191d,setsar=1,setpts=PTS-STARTPTS[outside];[2:v][screen]overlay=30:130:shortest=1[bg];[bg][outside]overlay=1400:130:shortest=1,fade=t=in:st=0:d=0.25,fade=t=out:st=21.75:d=0.25[out]'
 run(['-ss','154','-i',ROOT/'Media/more video.mp4','-ss','19','-i',ROOT/'Media/more video Outsider Perspective.MOV','-loop','1','-i',path,'-filter_complex',vf,'-map','[out]','-t','22','-r','30','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-an',A/'seg-5.mp4'])
 print('3/8 synchronized website + outside',flush=True)

def cloud_card():
 im=base(11,'Shared detection records','One database. Every screen.',['Detections stored in TigerData PostgreSQL','Shared across computers and phones'],'wide');d=ImageDraw.Draw(im)
 d.rounded_rectangle((660,430,1260,625),30,fill='#24433a',outline=GREEN,width=3)
 d.text((740,466),'TigerData',font=font(64,True),fill=WHITE);d.text((754,548),'Shared detection records',font=font(28),fill=GREEN)
 for x,title,sub in [(80,'COMPUTER','Browser dashboard'),(1330,'PHONE','Browser dashboard')]:
  d.rounded_rectangle((x,690,x+510,895),25,fill='#1c2b30');d.text((x+45,722),title,font=font(40,True),fill=WHITE);d.text((x+45,791),sub,font=font(29),fill=MUTED)
 d.line((810,625,335,690),fill=GREEN,width=5);d.line((1110,625,1585,690),fill=GREEN,width=5)
 d.text((640,927),'The same items, bins and history on each device.',font=font(28),fill=GREEN)
 encode_still(11,im,14);print('11 Shared TigerData',flush=True)

def media_panel(k,tag,title,lines,src,seconds,box,retain_note=None):
 im=base(k,tag,title,lines)
 if retain_note:ImageDraw.Draw(im).text((80,930),retain_note,font=font(25),fill=GREEN)
 encode_clip(k,im,src,0,seconds,box);print(f'{k} {tag}',flush=True)

im=base(1,'Litter-ally Trash','Show it.\nSort it.',['A mobile trash-sorting robot.','A connected web dashboard.']);photo(im,'IMG_2706.jpg',(1050,55,1840,950));encode_still(1,im,6);print('1 Intro',flush=True)
im=base(2,'The hardware','Two bins.\nOne build.',['Separate trash and recycling.','Independently controlled lids.','A camera and a mobile platform.']);photo(im,'IMG_3594.jpg',(1050,55,1430,950));photo(im,'IMG_3597.jpg',(1450,55,1840,950));encode_still(2,im,8);print('2 Hardware',flush=True)
media_panel(3,'On the move','A bin that\ncomes to you.',['Watch the mobile platform','move around the room.','The website provides','the driving controls.'],'movingVideo.MOV',24,(1120,35,516,916))
im=base(4,'Local AI model','What are you\nholding?',['Camera frames go to a local','CLIP vision model on the laptop.','It identifies the object and','assigns trash or recycling.']);photo(im,'IMG_3595.jpg',(1050,55,1840,950));encode_still(4,im,8);print('4 Local AI',flush=True)
paired_demo()
im=result_frame(6,'real-scanner.png','Bottle -> RECYCLING','Local model recognizes a plastic water bottle and selects the recycling bin.');encode_still(6,im,6);print('6 Recycling',flush=True)
im=result_frame(7,'real-trash.png','Chip bag -> TRASH','Local model recognizes a chip bag and selects the trash bin.');encode_still(7,im,6);print('7 Trash',flush=True)
im=base(8,'Automatic lid selection','Recognition chooses the bin.',['Camera image','Local AI detection','Corresponding lid opens'],'wide');d=ImageDraw.Draw(im)
for y,heading,items in [(430,'RECYCLING','Plastic water bottle  /  Cardboard'),(680,'TRASH','Chip bag  /  Paper towel')]:
 d.rounded_rectangle((80,y,1840,y+210),25,fill='#1e3032');d.text((115,y+26),heading,font=font(34,True),fill=GREEN);d.text((115,y+95),items,font=font(40),fill=WHITE);d.text((1220,y+100),'Matching lid opens',font=font(35,True),fill=GREEN)
encode_still(8,im,8);print('8 Bin routing',flush=True)
site_card(9,'Detection log','See what the AI recognized.',['Totals','Trash vs. recycling','Breakdown by item'],'log-site.png',(365,35,1800,710),10,'Actual detection-log interface with example records.')
site_card(10,'Shared detection history','Every detection has a record.',['Stored in TigerData PostgreSQL','Computers and phones see the same data'],'log-site.png',(365,1080,1800,1495),10,'Item, bin, match, source and time. Example records shown.')
cloud_card()
im=base(12,'Keyboard & touch','Drive it from the website.',['Directional controls','Adjustable throttle','A stop button'],'wide');encode_clip(12,im,'theRecording.mp4',19,12,(80,380,1760,580));print('12 Manual controls',flush=True)
im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
d.text((40,24),'LITTER-ALLY TRASH',font=font(32,True),fill=GREEN);d.text((690,20),'Voice control',font=font(45,True),fill=WHITE)
d.text((40,1005),'Listen to the spoken commands. Watch the driving state respond.',font=font(32),fill=WHITE)
encode_clip(13,im,'VoiceControlVideoWithMyMicSoTheyHearMe.mp4',0,19.6,(30,115,1860,850));print('13 Voice control with original microphone audio',flush=True)
media_panel(14,'Hand gestures','Point to steer.',['The laptop camera tracks','the hand landmarks.','Point to choose a direction.','Lower your hand to stop.'],'handGuestureProofVideoWebsiteView.mp4',13.1,(1050,55,790,895))
im=base(15,'Hand tracking','A closer look.',['The on-screen landmarks','follow the hand.','The website maps its direction','to a driving command.']);photo(im,'HandGuestureProof.png',(1050,55,1840,950));encode_still(15,im,6);print('15 Gesture close-up',flush=True)
im=base(16,'Gemini Sort Guide','Help with unfamiliar materials.',['Add a photo or describe the item','Get a practical sorting plan'],'wide')
p=Image.open(ROOT/'Media/Gemini-Integration.png').convert('RGB').crop((500,400,2780,1480));p=ImageOps.contain(p,(1760,540));im.paste(p,((W-p.width)//2,395))
ImageDraw.Draw(im).text((80,948),'Optional Gemini guidance for materials, separate components and next steps.',font=font(22),fill=GREEN)
encode_still(16,im,12);print('16 Gemini guide',flush=True)
im=base(17,'Litter-ally Trash','Recognize.\nSort.\nConnect.',['Local AI and automatic lids.','Keyboard, voice and gestures.','Shared records in TigerData.']);photo(im,'IMG_3596.jpg',(1050,55,1840,950));encode_still(17,im,7);print('17 Ending',flush=True)

# Original 112 BPM electronic instrumental, synthesized from scratch.
sr=48000;dur=191.7;n=int(sr*dur);music=np.zeros(n,dtype=np.float64);rng=np.random.default_rng(20261004)
def add(at,sound,gain=1):
 i=int(at*sr);end=min(n,i+len(sound))
 if i<n: music[i:end]+=sound[:end-i]*gain
def tone(freq,length):
 t=np.arange(int(length*sr))/sr;env=(1-np.exp(-t*40))*np.exp(-t*2.5)
 return (np.sin(2*np.pi*freq*t)+.18*np.sin(2*np.pi*2*freq*t))*env
beat=60/112
chords=[[130.81,164.81,196],[110,130.81,164.81],[87.31,110,130.81],[98,123.47,146.83]]
for bar in range(90):
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
lst=A/'segments.txt';lst.write_text('\n'.join("file 'seg-%d.mp4'"%i for i in range(1,18)))
run(['-f','concat','-safe','0','-i',lst,'-i',OUT/'original-instrumental.wav','-i',ROOT/'Media/VoiceControlVideoWithMyMicSoTheyHearMe.mp4','-filter_complex',"[1:a]loudnorm=I=-23:TP=-3:LRA=7,volume=0.12:enable='between(t,134,153.6)'[music];[2:a]atrim=0:19.6,asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-2:LRA=7,adelay=134000|134000,apad[voice];[music][voice]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[a]",'-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart','-t','191.7',OUT/'Litter-ally-Trash-YouTube.mp4'])
(OUT/'README.txt').write_text('Litter-ally Trash project walkthrough\n3:11.7 / 1920 x 1080 / 30 fps / H.264 + AAC\n\nIncludes the added movement, hand-tracking, voice-control clips and Gemini guide screenshot. Original microphone audio is retained during the voice section (2:14 to 2:33.6), with music lowered.\nPaired demo: more video.mp4 154-176 seconds and more video Outsider Perspective.MOV 19-41 seconds. Full requested website 162-175 interval included. The older IMG_3593.MOV test is omitted.\nRecognition uses the local CLIP model. Shared records are explained as stored in TigerData PostgreSQL; the app configuration confirms DATABASE_URL is set. Detection-log screenshots show labeled example records. No secrets are included.\nMusic is an original synthesized instrumental, no third-party samples.\nRebuild: BRH_Test/.venv/Scripts/python.exe output/video/build_video.py\n')
(OUT/'chapters.txt').write_text('0:00 Litter-ally Trash\n0:06 The hardware\n0:14 Rover movement\n0:38 Local AI recognition\n0:46 Website and outside view\n1:08 Recycling result\n1:14 Trash result\n1:20 Automatic lid selection\n1:28 Detection log\n1:38 Detection records\n1:48 Shared data in TigerData\n2:02 Keyboard and touch\n2:14 Voice control\n2:33 Hand gestures\n2:46 Hand-tracking close-up\n2:52 Gemini Sort Guide\n3:04 Litter-ally Trash\n')
print('DONE',flush=True)
