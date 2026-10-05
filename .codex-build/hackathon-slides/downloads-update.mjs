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
const p=await PresentationFile.importPptx(await FileBlob.load(path.join(out,'Litter-ally-Trash-Google-Slides.pptx')));
const C={bg:'#10191d',mint:'#a2efb6',white:'#eff7f4',muted:'#a3b8b6',rule:'#33464a'};
function text(s,content,x,y,w,h,size=28,color=C.white,bold=false){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=content;
 t.text.style={typeface:'Arial',fontSize:size,bold,color,autoFit:'none',wrap:'none',insets:{left:0,right:0,top:0,bottom:0},verticalAlignment:'top'};
}
async function image(s,name,x,y,w,h,alt){
 s.images.add({blob:new Uint8Array(await fs.readFile(path.join(build,'assets',name))),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});
}
async function start(title,n,notes){
 const s=p.slides.add();s.background.fill=C.bg;
 await image(s,'brand.png',55,45,266,40,'Litter-ally Trash branding from the demo');
 if(title)text(s,title,55,124,1170,78,50,C.white,true);
 s.shapes.add({geometry:'rect',position:{left:55,top:660,width:1170,height:1},fill:C.rule,line:{fill:'none',width:0}});
 text(s,'HACKATHON BUILD',55,677,350,25,16,C.muted,true);
 text(s,String(n).padStart(2,'0'),1190,677,35,25,16,C.muted,true);
 s.speakerNotes.textFrame.setText(notes);
 return s;
}
function block(s,title,body,y){text(s,title,55,y,700,35,27,C.mint,true);text(s,body,55,y+43,700,75,25,C.muted);}
{
 const s=await start('Photon messaging companion',8,'Sources: spectrum/README.md; BRH_Test/companion.py Companion.command and Companion.advice; spectrum/src/index.ts. Photon Spectrum transports iMessage or Telegram messages to the authenticated Python bridge. Dashboard chat shares the same companion. All interfaces read the shared Pilot records. Advice uses xAI with local fallback. Manual collections require an exact confirmation code within five minutes and duplicate request IDs cannot award points twice. The model has no hardware or write tools. Screenshot: user-supplied C:/Users/John/Downloads/Photon.png, cropped to the question and reply. Shown progress counts are from that recorded conversation, not current totals.');
 text(s,'iMessage, Telegram and dashboard chat',55,218,700,44,29,C.white);
 block(s,'SHARED PROGRESS','Reads the same Pilot history\nas the dashboard.',284);
 block(s,'SORTING ADVICE','Answers item questions with\nrecycling context.',398);
 block(s,'CONFIRMED DROPS','A five-minute code confirms\na proposed collection record.',512);
 await image(s,'photon-conversation.png',785,241,440,352,'Actual iMessage question and Photon companion reply with shared progress and recycling advice');
 text(s,'Actual iMessage conversation',785,602,440,26,18,C.muted);
 text(s,'Driving stays with the dashboard controls.',55,629,1170,25,18,C.muted);
}
{
 const s=await start('',9,'Closing brand slide. User-supplied original mascot: C:/Users/John/Downloads/literarlytrash.png, cropped only to transparent bounds. Project sources: docs/architecture.md; classifier_service.py; lid.py; BRH_Test/database.py.');
 text(s,'Recognize.\nSort.\nConnect.',55,174,635,310,80,C.white,true);
 text(s,'Local vision. Automatic lids.\nShared recycling history.',55,532,670,85,29,C.muted);
 await image(s,'mascot.png',745,132,480,485,'Original Litter-ally Trash trash-can mascot');
}
const candidate=path.join(build,'downloads-candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=path.join(out,'Litter-ally-Trash-Google-Slides-v2.pptx');
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,
 pythonExecutable:'C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],
 explicitTotalSlideCount:9,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'design',families:['Arial']},verifyArtifactToolImport:true,
 receiptPath:path.join(build,'downloads-validation.json')});
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(final));
const images=path.join(out,'images-v2');
await fs.mkdir(images,{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
 const png=await finalDeck.export({slide:finalDeck.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(path.join(images,`${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log('Rendered',i+1);
}
const oldCopy=await fs.readFile(path.join(out,'slide-copy.md'),'utf8');
await fs.writeFile(path.join(out,'slide-copy-v2.md'),oldCopy+'\n\n## 8. Photon messaging companion\n\niMessage, Telegram and dashboard chat share the same companion. It reads the shared Pilot progress and provides sorting advice. A five-minute confirmation code authorizes a proposed collection record. Driving stays with the dashboard controls.\n\n## 9. Recognize. Sort. Connect.\n\nLocal vision. Automatic lids. Shared recycling history.\n');
console.log(final);
