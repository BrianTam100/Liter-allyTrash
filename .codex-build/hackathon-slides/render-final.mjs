import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const dir='C:/Users/John/Desktop/codingProjects/SortRover/output/hackathon-slides';
const p=await PresentationFile.importPptx(await FileBlob.load(`${dir}/Litter-ally-Trash-Hackathon-v2.pptx`));
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(`${dir}/images/${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await blob.arrayBuffer()));
 console.log('Final slide',i+1);
}
