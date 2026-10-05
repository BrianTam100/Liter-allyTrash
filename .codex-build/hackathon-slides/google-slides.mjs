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
const {finalizePresentation,resolvePresentationFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const family=resolvePresentationFont({fontFamily:'Arial'});
const p=await PresentationFile.importPptx(await FileBlob.load(path.join(out,'Litter-ally-Trash-Hackathon-v2.pptx')));
for(const s of p.slides.items)for(const shape of s.shapes.items){
 if(shape.text)shape.text.style={typeface:family};
}
const candidate=path.join(build,'google-candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=path.join(out,'Litter-ally-Trash-Google-Slides.pptx');
const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,
 pythonExecutable:'C:/Users/John/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],
 explicitTotalSlideCount:7,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'design',families:[family]},verifyArtifactToolImport:true,
 receiptPath:path.join(build,'google-validation.json')});
console.log('Validated:',result.finalPath);
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(final));
await fs.mkdir(path.join(build,'google-previews'),{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
 const png=await finalDeck.export({slide:finalDeck.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(build,'google-previews',`${i+1}.png`),new Uint8Array(await png.arrayBuffer()));
}
console.log('All seven slides rendered');
