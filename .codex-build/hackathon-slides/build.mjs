import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const root='C:/Users/John/Desktop/codingProjects/SortRover';
const build=path.join(root,'.codex-build/hackathon-slides');
const out=path.join(root,'output/hackathon-slides');
const skill='C:/Users/John/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const runtimePython='C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
process.env.RUNTIME_NODE_MODULES='C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE='C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe';
const {finalizePresentation,resolvePresentationFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const family=resolvePresentationFont({fontFamily:'Segoe UI'});
console.log('Font:',family);
const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={bg:'#10191d',mint:'#a2efb6',white:'#eff7f4',muted:'#a3b8b6',rule:'#33464a'};
const copy=[];
const brandBytes=new Uint8Array(await fs.readFile(path.join(build,'assets/brand.png')));
function text(s,content,x,y,w,h,size=28,color=C.white,bold=false){
  const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  t.text=content;
  t.text.style={typeface:family,fontSize:size,bold,color,autoFit:'none',wrap:'none',insets:{left:0,right:0,top:0,bottom:0},verticalAlignment:'top'};
  return t;
}
function start(title,n,notes){
  const s=p.slides.add();s.background.fill=C.bg;
  s.images.add({blob:brandBytes,contentType:'image/png',alt:'Litter-ally Trash branding from the demo',fit:'contain',position:{left:55,top:45,width:266,height:40}});
  if(title)text(s,title,55,124,1170,78,50,C.white,true);
  const rule=s.shapes.add({geometry:'rect',position:{left:55,top:660,width:1170,height:1},fill:C.rule,line:{fill:'none',width:0}});
  text(s,'HACKATHON BUILD',55,677,350,25,16,C.muted,true);
  text(s,String(n).padStart(2,'0'),1190,677,35,25,16,C.muted,true);
  s.speakerNotes.textFrame.setText(notes);
  return s;
}
async function photo(s,name,x,y,w,h,alt,fit='contain'){
  s.images.add({blob:new Uint8Array(await fs.readFile(path.join(build,'assets',name))),contentType:name.endsWith('.png')?'image/png':'image/jpeg',alt,fit,position:{left:x,top:y,width:w,height:h}});
}
function block(s,title,body,y,w=710){text(s,title,55,y,w,35,27,C.mint,true);text(s,body,55,y+43,w,75,25,C.muted);}

// 1. Project cover.
{
 const s=start('',1,'Project overview. Sources: README.md; docs/hardware.md; docs/architecture.md. Hardware photograph: Media/IMG_3596.jpg. Photo preserves the actual prototype.');
 text(s,'Recognize.\nSort.\nConnect.',55,174,635,310,80,C.white,true);
 text(s,'A mobile trash-sorting rover\nwith local vision and a shared dashboard.',55,518,650,85,29,C.muted);
 await photo(s,'cover.jpg',745,45,480,585,'Actual two-bin rover with one servo lid open','cover');
 copy.push(['Recognize. Sort. Connect.','A mobile trash-sorting rover with local vision and a shared dashboard.']);
}
// 2. Architecture, including the two separate Raspberry Pis in the actual build.
{
 const s=start('The software and hardware',2,'Sources: docs/architecture.md, especially Two Pis in practice; docs/hardware.md; web_server.py; BRH_Test/rover_bridge.py; BRH_Test/driveController/driveController.ino. The laptop hosts Flask and CLIP. Separate Pi processes handle drive and camera/lids. TigerData is a remote PostgreSQL service. Hardware photo: Media/IMG_3597.jpg.');
 block(s,'LAPTOP','Flask serves the dashboard.\nCLIP runs inference on the laptop.',226,735);
 block(s,'TWO RASPBERRY PIS','One relays drive commands.\nThe other streams the camera and moves lids.',362,735);
 block(s,'ARDUINO + CNC SHIELD','USB serial reaches the motor controller.\nFour steppers drive the mecanum wheels.',498,735);
 await photo(s,'architecture.jpg',850,220,375,408,'Actual rover chassis, Raspberry Pi and mecanum wheels','cover');
 copy.push(['The software and hardware','Laptop: Flask dashboard and local CLIP inference. Two Raspberry Pis: drive relay, and camera/lid control. Arduino plus CNC shield: four stepper motors and mecanum wheels.']);
}
// 3. Explain the supported targets and stable recognition instead of claiming broad accuracy.
{
 const s=start('Local CLIP recognition',3,'Sources: classifier.py MODEL_ID, TARGETS, Classifier.predict; classifier_service.py ItemLock.READINGS and LOCK_SECONDS. Default model is openai/clip-vit-large-patch14. The model compares the whole frame with text candidates, including non-target labels. Only four item families are reported. Three or more readings spanning at least 0.5 seconds form a lock. Relative scores are candidate comparisons, not accuracy probabilities. Screenshot: source recording at 167.5 seconds, actual bottle and recycling result.');
 text(s,'The laptop compares camera\nframes with text labels.',55,225,430,92,29,C.muted);
 text(s,'CLIP ViT-L/14',55,333,425,36,25,C.white,true);
 text(s,'RECYCLING',55,402,425,30,22,C.mint,true);
 text(s,'Bottle and cardboard',55,438,425,43,28);
 text(s,'TRASH',55,508,425,30,22,C.mint,true);
 text(s,'Paper towel and chip bag',55,544,425,43,28);
 await photo(s,'scanner.png',495,231,730,315,'Actual bottle preview and plastic water bottle recycling result');
 text(s,'Three readings over at least 0.5 seconds\nproduce a stable item lock.',505,560,710,75,25,C.muted);
 text(s,'Other labels return no supported item. Match scores compare candidates.',55,627,1170,25,18,C.muted);
 copy.push(['Local CLIP recognition','CLIP ViT-L/14 compares camera frames with text labels. Bottle and cardboard map to recycling. Paper towel and chip bag map to trash. At least three readings across 0.5 seconds create a stable lock. Other labels return no supported item. Relative scores are not accuracy probabilities.']);
}
// 4. The real lid control path.
{
 const s=start('A detection opens the matching lid',4,'Sources: classifier_service.py Service.track; lid.py RemoteLid and Lid; lid_server.py; docs/hardware.md. Live locked readings trigger open Trash or open Recyclable through UDP 5006. The lid Pi controls PCA9685 over I2C, channel 0 trash and channel 3 recycling. HOLD_SECONDS=5 after the last reading. Lid automation must be enabled. Photos do not open lids. Image: Media/IMG_3595.jpg.');
 block(s,'LIVE ITEM LOCK','The laptop sends the bin command\nover Wi-Fi UDP to the lid Pi.',228,690);
 block(s,'CALIBRATED SERVO LIDS','The Pi drives the PCA9685 over I²C.\nEach bin has its own servo channel.',370,690);
 block(s,'AUTOMATIC CLOSE','The lid stays open for about 5 seconds\nafter the last matching reading.',512,690);
 await photo(s,'lids.jpg',815,229,410,397,'Actual servos, cardboard lids, PCA9685 and Raspberry Pi','cover');
 text(s,'Automatic lids use live scans when enabled. Photo uploads do not open lids.',55,629,1170,25,18,C.muted);
 copy.push(['A detection opens the matching lid','A locked live item sends a bin command over Wi-Fi UDP to the lid Pi. The Pi uses PCA9685 over I2C to drive calibrated servos. Each bin has its own channel. The lid stays open about five seconds after the last matching reading. Photos do not open lids.']);
}
// 5. Controls, cloud voice and local hand tracking remain separate from CLIP.
{
 const s=start('Website, voice and hand controls',5,'Sources: BRH_Test/rover_bridge.py set_mode, _camera_loop, _watchdog; BRH_Test/voice_control.py DRIVE_TOOL and DIRECTION_TO_CMD; docs/hardware.md. Website directions support keyboard, touch/mouse. Grok voice uses xAI realtime WebSocket and invokes drive_rover. MediaPipe runs locally; wrist-to-index-tip angle is rounded to five degrees and sent over Bluetooth. Wi-Fi receiver supports WASD, not angles. One driving session at a time. Heartbeat loss beyond 1.5 seconds stops/releases rover. Hand image: Media/HandGuestureProof.png.');
 block(s,'WEBSITE CONTROLS','Direction buttons and throttle\nsend commands through the rover bridge.',224,755);
 block(s,'GROK VOICE','Spoken directions call a drive tool.\nThe bridge sends the motor command.',350,755);
 block(s,'MEDIAPIPE HAND TRACKING','Wrist-to-fingertip angle sets direction.\nBluetooth carries the angle to the rover.',476,755);
 await photo(s,'gestures.png',890,211,335,397,'Recorded MediaPipe hand landmarks and rover driving state','contain');
 text(s,'One driving browser at a time. A missing heartbeat stops the rover after 1.5 seconds.',55,628,1170,26,18,C.muted);
 copy.push(['Website, voice and hand controls','Website buttons and throttle use the rover bridge. Grok voice calls a drive tool for spoken directions. Local MediaPipe hand tracking converts wrist-to-fingertip angle to direction over Bluetooth. One browser controls the rover at a time. Missing heartbeats stop the rover after 1.5 seconds.']);
}
// 6. Actual shared records and collection semantics.
{
 const s=start('Every detection has a record',6,'Sources: BRH_Test/database.py initialize, add_detection, add_collection, bin_contents, empty_bin; dashboard_classifier.py log_detection and auto_recorded; docs/architecture.md Logging and points. Each locked live scan and each photo records item, bin, score, source, time. Unique scan_id avoids duplicate rows as frames repeat. With configured DATABASE_URL the backend uses TigerData PostgreSQL, otherwise SQLite. Lids opening auto-records one collection event per locked scan. The camera does not verify a physical deposit. Photos and disabled lids require manual confirmation. No images stored in the ledger. Screenshot: output/video/assets/live-log-site.png. README.md manual-confirmation wording is older than the current automatic collection implementation.');
 text(s,'TigerData PostgreSQL',55,226,680,48,35,C.mint,true);
 text(s,'Computers and phones access the same history\nthrough the dashboard.',55,281,1170,80,29,C.muted);
 await photo(s,'log.png',55,385,1170,242,'Actual detection log with item, bin, match, source and time');
 text(s,'One scan ID prevents repeat frames from creating duplicate records.',55,359,1170,30,22,C.white);
 text(s,'The ledger stores metadata, not camera images. Lid openings record collection events.',55,628,1170,26,18,C.muted);
 copy.push(['Every detection has a record','TigerData PostgreSQL stores shared history that computers and phones access through the dashboard. Locked live detections and photo analyses record the item, bin, match, source and time. A unique scan ID prevents duplicate rows. The ledger stores metadata, not camera images. Opening a lid records a collection event but does not sensor-verify a deposit.']);
}
// 7. Gemini's actual scope, with the real guide screenshot.
{
 const s=start('Gemini guidance for unfamiliar items',7,'Sources: BRH_Test/GEMINI.md; BRH_Test/gemini_guide.py; web/gemini.js. Guide accepts question, optional location and selected photo. Photos are decoded, resized and stripped of EXIF. Submitted content goes to Google Gemini. It is a separate advisory flow with no drive, lid or ledger tools and no live municipal-rule lookup. Screenshot: Media/Gemini-Integration.png.');
 text(s,'Upload a photo or ask about\nan unfamiliar item.',55,232,715,92,30,C.mint,true);
 text(s,'Material guidance\nPreparation steps\nReuse ideas',55,364,715,145,31,C.white);
 text(s,'Advice stays separate from local CLIP\nrecognition and rover control.',55,533,715,80,26,C.muted);
 await photo(s,'gemini.png',800,233,425,387,'Actual Gemini Sort Guide sorting plan interface');
 text(s,'Gemini processes submitted content in the cloud. The guide does not record drops.',55,628,1170,26,18,C.muted);
 copy.push(['Gemini guidance for unfamiliar items','Submit a photo or describe an item for material guidance, preparation steps and reuse ideas. The cloud guide is separate from the local CLIP scanner. It provides advice without controlling the rover or recording drops. Verify disposal rules locally.']);
}

await fs.mkdir(out,{recursive:true});
await fs.mkdir(path.join(out,'images'),{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const slide=p.slides.items[i];
 const png=await p.export({slide,format:'png',scale:1.5});
 await fs.writeFile(path.join(out,'images',`${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 await fs.writeFile(path.join(build,`slide-${i+1}.layout.json`),await (await slide.export({format:'layout'})).text());
 console.log('Rendered',i+1);
}
await fs.writeFile(path.join(out,'slide-copy.md'),copy.map((c,i)=>`## ${i+1}. ${c[0]}\n\n${c[1]}`).join('\n\n'));
const draft=path.join(build,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(draft);
const final=path.join(out,'Litter-ally-Trash-Hackathon-v2.pptx');
console.log(await finalizePresentation({workspaceDir:root,candidatePath:draft,finalPath:final,pythonExecutable:runtimePython,
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],
 explicitTotalSlideCount:7,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'design',families:[family]},verifyArtifactToolImport:true,
 receiptPath:path.join(build,'validation-v2.json')}));
