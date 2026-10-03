const $ = id => document.getElementById(id);
let ready = false, running = false, stream = null, generation = 0, pending = null, count = 0;
const canvas = document.createElement('canvas');
function sizeGuide() {
  const video = $('video');
  if (!video.videoWidth) return;
  const scale = Math.min(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight);
  $('guide').style.width = (Math.min(video.videoWidth, video.videoHeight) * .8 * scale) + 'px';
}
window.addEventListener('resize', sizeGuide);
function resetResult() {
  pending = null; count = 0; $('label').textContent = 'Ready for an item'; $('label').className = '';
  $('score').textContent = '—'; $('score-bar').style.width = '0%';
  $('candidates').replaceChildren(); $('hint').textContent = 'Show one item against a plain background.';
}
function stop() {
  running = false; generation++;
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null; $('video').srcObject = null;
  if ($('preview').dataset.streaming) {
    $('preview').removeAttribute('src');
    delete $('preview').dataset.streaming;
    $('preview').hidden = true; $('placeholder').hidden = false;
  }
  $('stop').hidden = true; $('start').hidden = $('source').value === 'upload';
  $('start').disabled = !ready; $('guide').hidden = true;
}
function sourceChanged() {
  stop(); resetResult(); $('message').textContent = '';
  $('video').hidden = true; $('preview').hidden = true; $('placeholder').hidden = false;
  $('upload-label').hidden = $('source').value !== 'upload';
  $('start').textContent = $('source').value === 'server' ? 'Start detection' : 'Start camera';
}
async function request(path, body, live = false) {
  const headers = {'X-Trash-UI':'1'};
  if (live) headers['X-Trash-Live'] = '1';
  const response = await fetch(path, {method: 'POST', headers, body});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function show(result, live) {
  let label = result.label;
  if (live) {
    if (/^(No trash|Hold|Image)/.test(label)) { pending = null; count = 0; }
    else { count = pending === label ? count + 1 : 1; pending = label;
      if (count < 2) label = 'Hold still — checking item'; }
  }
  const bin = label.startsWith('Hold') ? null : result.category;
  $('label').textContent = bin || label;
  $('label').className = bin ? bin.toLowerCase() : '';
  $('hint').textContent = label.startsWith('Hold') ? 'Confirming with a second reading.'
    : (bin ? label[0].toUpperCase() + label.slice(1) + '. ' : '') + (result.drop_off
      ? 'Take it to a drop-off recycling site, not the curbside bin.'
      : 'Try another angle if this doesn’t look right.');
  $('score').textContent = Math.round(result.score * 100) + '%';
  $('score-bar').style.width = Math.round(result.score * 100) + '%';
  $('candidates').replaceChildren(...result.alternatives.map(item => {
    const li = document.createElement('li'), value = document.createElement('span');
    li.textContent = item.label; value.textContent = Math.round(item.score * 100) + '%';
    li.append(value); return li;
  }));
  $('timing').textContent = `Last inference: ${result.seconds.toFixed(2)}s · Processed locally`;
}
async function frameBlob() {
  const video = $('video'), size = Math.floor(Math.min(video.videoWidth, video.videoHeight) * .8);
  if (!size) throw new Error('Camera is not supplying frames.');
  canvas.width = canvas.height = 512;
  canvas.getContext('2d').drawImage(video, (video.videoWidth-size)/2, (video.videoHeight-size)/2, size, size, 0, 0, 512, 512);
  return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .85));
}
async function loop(token) {
  while (running && generation === token) {
    try {
      const serverCamera = $('source').value === 'server';
      const body = serverCamera ? undefined : await frameBlob();
      if (!running || generation !== token) return;
      const result = await request(serverCamera ? '/api/camera' : '/api/predict', body, true);
      if (!running || generation !== token) return;
      show(result, true); $('message').textContent = '';
    } catch (error) {
      if (generation !== token) return;
      stop(); $('message').textContent = error.message; return;
    }
    await new Promise(resolve => setTimeout(resolve, 350));
  }
}
$('start').onclick = async () => {
  $('message').textContent = ''; $('start').disabled = true;
  const token = ++generation;
  try {
    if ($('source').value === 'browser') {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Browser camera access requires localhost or HTTPS. On a Pi network address, use the connected camera or upload a photo.');
      const acquired = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment', width: {ideal: 640}}, audio: false});
      if (generation !== token) { acquired.getTracks().forEach(t => t.stop()); return; }
      // Mirror front-facing webcams for natural left/right movement in the preview.
      // Keep rear cameras and the original frames sent to the model unmirrored.
      const facingMode = acquired.getVideoTracks()[0].getSettings().facingMode;
      $('video').classList.toggle('mirrored', facingMode !== 'environment');
      stream = acquired; $('video').srcObject = stream; await $('video').play();
      if (generation !== token) return;
      $('video').hidden = false; $('preview').hidden = true; $('placeholder').hidden = true; $('guide').hidden = false;
      sizeGuide();
    } else if ($('source').value === 'server') {
      const result = await request('/api/camera/start');
      if (generation !== token) return;
      $('preview').onload = null;
      $('preview').dataset.streaming = 'true';
      $('preview').src = result.url;
      $('preview').hidden = false; $('video').hidden = true; $('placeholder').hidden = true;
    }
    running = true; resetResult(); $('start').hidden = true; $('stop').hidden = false; loop(token);
  } catch (error) { if (generation === token) { stop(); $('message').textContent = error.message; } }
};
$('stop').onclick = stop;
$('source').onchange = sourceChanged;
$('file').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  if (!ready) { $('message').textContent = 'Wait for the model to finish loading.'; event.target.value = ''; return; }
  stop(); resetResult(); const token = generation;
  if (file.size > 8 * 1024 * 1024) { $('message').textContent = 'Choose an image smaller than 8 MB.'; event.target.value = ''; return; }
  const url = URL.createObjectURL(file);
  $('preview').src = url; $('preview').onload = () => URL.revokeObjectURL(url);
  $('preview').hidden = false; $('placeholder').hidden = true; $('message').textContent = 'Recognizing image…';
  try { const result = await request('/api/predict', file); if (token === generation) { show(result, false); $('message').textContent = ''; } }
  catch(error) { if (token === generation) $('message').textContent = error.message; }
  event.target.value = '';
};
async function status() {
  try {
    const response = await fetch('/api/status'); const result = await response.json();
    if (result.error) { $('status').textContent = 'Model unavailable'; $('message').textContent = result.error; return; }
    if (result.ready) { ready = true; $('status').textContent = 'Model ready'; $('dot').style.background = '#7b9c65'; $('start').disabled = false; return; }
  } catch { $('status').textContent = 'Connecting to server…'; }
  setTimeout(status, 2000);
}
window.addEventListener('pagehide', stop);
status();
