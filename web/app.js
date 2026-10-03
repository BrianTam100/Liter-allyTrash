const $ = id => document.getElementById(id);
let ready = false, running = false, stream = null, generation = 0;
const BOX = 1; // Use the entire camera frame for detection and its guide.
const canvas = document.createElement('canvas');
function sizeGuide() {
  const video = $('video');
  if (!video.videoWidth) return;
  const scale = Math.min(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight);
  $('guide').style.width = (video.videoWidth * BOX * scale) + 'px';
  $('guide').style.height = (video.videoHeight * BOX * scale) + 'px';
}
window.addEventListener('resize', sizeGuide);
function resetResult() {
  $('label').textContent = 'Ready for an item'; $('label').className = '';
  $('score').textContent = '—'; $('score-bar').style.width = '0%';
  $('candidates').replaceChildren(); $('hint').textContent = 'Show one item against a plain background.';
}
function stop() {
  running = false; generation++; document.body.classList.remove('live');
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
  if (!response.ok) throw Object.assign(new Error(result.error || 'Request failed'), {status: response.status});
  return result;
}
function show(result) {
  // Live readings come with a state: checking (comparing readings), locked
  // (best match held until the item is removed) or empty (no item in view).
  const checking = result.state === 'checking', label = result.label;
  const bin = checking ? null : result.category;
  const item = label[0].toUpperCase() + label.slice(1);
  $('label').textContent = checking ? 'Checking item…'
    : bin ? `${item} — ${bin === 'Recyclable' ? 'Recycling' : 'Trash'}` : item;
  $('label').className = bin ? bin.toLowerCase() : '';
  $('hint').textContent = checking ? `Hold still — comparing readings (${result.checks}/${result.of}).`
    : (result.drop_off
      ? 'Take it to a drop-off recycling site, not the curbside bin. '
      : '') + (result.state === 'locked' ? 'Remove the item to scan the next one.'
      : result.drop_off ? '' : 'Try another angle if this doesn’t look right.');
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
  const video = $('video'), width = Math.floor(video.videoWidth * BOX), height = Math.floor(video.videoHeight * BOX);
  if (!width || !height) throw new Error('Camera is not supplying frames.');
  const scale = 640 / Math.max(width, height);
  canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
  canvas.getContext('2d').drawImage(video, (video.videoWidth-width)/2, (video.videoHeight-height)/2, width, height, 0, 0, canvas.width, canvas.height);
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
      show(result); $('message').textContent = '';
    } catch (error) {
      if (generation !== token) return;
      // Another screen watching the same camera is using the detector; try again.
      if (error.status !== 429) { stop(); $('message').textContent = error.message; return; }
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
    running = true; document.body.classList.add('live'); sizeGuide(); resetResult(); $('start').hidden = true; $('stop').hidden = false; loop(token);
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
  try { const result = await request('/api/predict', file); if (token === generation) { show(result); $('message').textContent = ''; } }
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
