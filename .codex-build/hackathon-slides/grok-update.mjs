import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const root='C:/Users/John/Desktop/codingProjects/SortRover';
const build=path.join(root,'.codex-build/hackathon-slides');
const out=path.join(root,'output/hackathon-slides');
const skill='C:/Users/John/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
process.env.RUNTIME_NODE_MODULES='C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE='C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe';
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const p=await PresentationFile.importPptx(await FileBlob.load('C:/Users/John/Downloads/Litter-ally-Trash-Google-Slides-v2.pptx'));
const C={bg:'#10191d',mint:'#a2efb6',white:'#eff7f4',muted:'#a3b8b6',rule:'#33464a'};
function text(s,content,x,y,w,h,size=28,color=C.white,bold=false){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=content;t.text.style={typeface:'Arial',fontSize:size,bold,color,autoFit:'none',wrap:'none',insets:{left:0,right:0,top:0,bottom:0},verticalAlignment:'top'};
}
async function image(s,name,x,y,w,h,alt){
 s.images.add({blob:new Uint8Array(await fs.readFile(path.join(build,'assets',name))),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});
}
const s=p.slides.add();s.background.fill=C.bg;
await image(s,'brand.png',55,45,266,40,'Litter-ally Trash branding from the demo');
text(s,'Grok voice control',55,124,1170,78,50,C.white,true);
function block(title,body,y){text(s,title,55,y,710,35,27,C.mint,true);text(s,body,55,y+43,710,75,25,C.muted);}
block('LAPTOP MICROPHONE','Audio streams to xAI’s realtime API\nwhen voice control is enabled.',228);
block('GROK TOOL CALL','Grok interprets the spoken request and\ncalls drive_rover with a direction.',365);
block('ROBOT COMMAND','The bridge sends motion or stop through\nthe drive Pi to the Arduino.',502);
await image(s,'grok-voice-interface.png',785,230,440,152,'Actual website Grok voice controls with listening status');
text(s,'SPOKEN DIRECTIONS',785,421,440,30,22,C.mint,true);
text(s,'“Go forward.”\n“Turn left.”\n“Stop.”',785,464,440,132,30,C.white);
text(s,'Voice uses cloud AI. The CLIP item classifier runs locally.',55,629,1170,25,18,C.muted);
s.shapes.add({geometry:'rect',position:{left:55,top:660,width:1170,height:1},fill:C.rule,line:{fill:'none',width:0}});
text(s,'HACKATHON BUILD',55,677,350,25,16,C.muted,true);
text(s,'06',1190,677,35,25,16,C.muted,true);
s.speakerNotes.textFrame.setText('Sources: BRH_Test/voice_control.py SAMPLE_RATE, REALTIME_URL, DRIVE_TOOL, DIRECTION_TO_CMD, VoiceDrive._session and _apply_drive; BRH_Test/rover_bridge.py set_mode, _assisted_command and _send; docs/hardware.md. Voice captures the laptop microphone at 24 kHz PCM16 and streams it to the xAI realtime WebSocket, with model grok-voice-latest. A drive_rover function call maps forward/backward/left/right/stop to w/s/a/d/x. Left and right spin the rover in place. Commands pass through the existing bridge and drive Pi to the Arduino, using Bluetooth serial or Wi-Fi UDP. A requested duration schedules a stop. The bridge checks the driving owner, current voice mode and heartbeat, and gives recent manual input priority. Cloud voice is separate from local CLIP recognition. Screenshot: output/video/assets/voice-reference.jpg, cropped to the actual voice interface. This recorded UI uses demo mode; the screenshot shows the listening controls, not evidence of hardware movement.');
s.moveTo(5);
for(let i=0;i<p.slides.items.length;i++){
 const slide=p.slides.items[i];
 for(const shape of slide.shapes.items){
  if(shape.position.left>=1180 && shape.position.top>=670 && shape.text)shape.text=String(i+1).padStart(2,'0');
 }
}
console.log('Order:',p.slides.items.map(sl=>sl.shapes.items.filter(sh=>sh.position.top===124).map(sh=>String(sh.text)).join(' ')));
const candidate=path.join(build,'grok-candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=path.join(out,'Litter-ally-Trash-Google-Slides-v3.pptx');
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,
 pythonExecutable:'C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],
 explicitTotalSlideCount:10,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,
 receiptPath:path.join(build,'grok-validation.json')});
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(final));
const images=path.join(out,'images-v3');await fs.mkdir(images,{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
 const png=await finalDeck.export({slide:finalDeck.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(path.join(images,`${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log('Rendered',i+1);
}
const oldCopy=await fs.readFile(path.join(out,'slide-copy-v2.md'),'utf8');
const parts=oldCopy.split(/(?=^## )/m).filter(x=>x.trim());
parts.splice(5,0,'## 6. Grok voice control\n\nThe laptop microphone streams audio to xAI’s realtime API when enabled. Grok interprets spoken directions and calls drive_rover. The bridge maps the direction to a motion or stop command, relayed through the drive Pi to the Arduino. Voice uses cloud AI while CLIP recognition runs locally.\n\n');
await fs.writeFile(path.join(out,'slide-copy-v3.md'),parts.map((part,i)=>part.replace(/^## \d+\./,`## ${i+1}.`)).join(''));
console.log(final);
