(() => {
"use strict";

const csrf = document.querySelector('meta[name="csrf-token"]').content;
const signedIn = document.body.dataset.signedIn === "true";
const $ = (selector) => document.querySelector(selector);

async function api(path, data, wait = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), wait);
  try {
    const response = await fetch(path, {
      method: data === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "That action could not be completed. Try again.");
    return result;
  } catch (error) {
    if (error.name === "AbortError" || error instanceof TypeError) {
      throw new Error("Connection interrupted. Reconnect and try again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

let toastTimer;
function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.hidden = true; }, 5500);
}

function formatTimes(root) {
  root.querySelectorAll(".local-time").forEach((element) => {
    const date = new Date(element.dateTime);
    if (!Number.isNaN(date.getTime())) element.textContent = new Intl.DateTimeFormat(undefined, {month:"short", day:"numeric", hour:"numeric", minute:"2-digit"}).format(date);
  });
}
formatTimes(document);

// Swap in fresh history and detections without a full page reload.
async function refreshPanels() {
  const response = await fetch(location.pathname, {headers:{"Accept":"text/html"}});
  if (!response.ok) return;
  const fresh = new DOMParser().parseFromString(await response.text(), "text/html");
  for (const selector of [".history-panel", ".detections-preview"]) {
    const current = $(selector), next = fresh.querySelector(selector);
    if (current && next) { current.replaceWith(next); formatTimes(next); }
  }
}

const collectionForm = $("#collection-form");
if (collectionForm) {
  let requestId = null;
  let attemptedPayload = null;
  collectionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = collectionForm.querySelector('button[type="submit"]');
    const feedback = $("#collection-feedback");
    const fields = new FormData(collectionForm);
    const payload = {item_name: fields.get("item_name").trim(), category: fields.get("category"), count: Number(fields.get("count"))};
    const signature = JSON.stringify(payload);
    if (!requestId || signature !== attemptedPayload) requestId = crypto.randomUUID();
    attemptedPayload = signature;
    button.disabled = true;
    feedback.classList.remove("error");
    feedback.textContent = "Recording your drop…";
    try {
      const scanId = collectionForm.dataset.scanId;
      const result = await api(scanId ? "/api/classifier/confirm" : "/api/collections", {...payload, request_id: requestId, scan_id:scanId});
      requestId = null;
      const points = payload.category === "recycling" ? payload.count * 10 : 0;
      feedback.textContent = result.saved ? (points ? `Drop recorded. +${points} recycling points!` : "Trash drop recorded in your history.") : "This drop was already recorded. Your score is up to date.";
      for (const name of ["points", "recycled", "items", "collections"]) $("#stat-" + name).textContent = result.stats[name];
      collectionForm.reset();
      delete collectionForm.dataset.scanId;
      $("#entry-source").textContent = "Manual entry · Confirm only items you have put in the bin.";
      button.disabled = false;
      refreshPanels().catch(() => {});
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.add("error");
      button.disabled = false;
    }
  });
  document.addEventListener("trash:recognized", (event) => {
    const result = event.detail;
    $("#item-name").value = result.label;
    const category = result.category === "Recyclable" ? "recycling" : "trash";
    collectionForm.querySelector(`[name="category"][value="${category}"]`).checked = true;
    $("#item-count").value = "1";
    collectionForm.dataset.scanId = result.scan_id;
    $("#entry-source").textContent = "Recognized item · Confirm after putting it in the correct bin.";
    $("#collection-feedback").textContent = "Item added below. Confirm your drop to update your score.";
    collectionForm.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'center'});
    $("#item-name").focus({preventScroll:true});
  });
  collectionForm.addEventListener("input", (event) => {
    if (event.target.name === "count") return;
    delete collectionForm.dataset.scanId;
    $("#entry-source").textContent = "Manual entry · Confirm only items you have put in the bin.";
  });
}

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  if (!$('source')) return;
  const signedIn = document.body.dataset.signedIn === 'true';
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const canvas = document.createElement('canvas');
  let ready = false, running = false, stream = null, generation = 0;
  let cameraGeneration = null, owned = false, latestResult = null;
  let heartbeatTimer = null, requestController = null, statusTimer = null, objectUrl = null;

  function message(text, error = false) {
    $('message').textContent = text;
    $('message').classList.toggle('error', error);
  }

  function sizeGuide() {
    const video = $('video');
    if (!video.videoWidth) return;
    const scale = Math.min(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight);
    $('guide').style.width = (video.videoWidth * scale) + 'px';
    $('guide').style.height = (video.videoHeight * scale) + 'px';
  }

  async function request(path, body, live = false, cancellable = false) {
    const controller = new AbortController();
    if (cancellable) requestController = controller;
    const timeout = setTimeout(() => controller.abort(), 30000);
    const headers = {'X-CSRF-Token':csrf, 'X-Trash-UI':'1'};
    if (live) { headers['X-Trash-Live'] = '1'; headers['X-Trash-Session'] = String(cameraGeneration); }
    const binary = body instanceof Blob;
    if (!binary) headers['Content-Type'] = 'application/json';
    try {
      const response = await fetch(path, {method:'POST', headers,
        body:binary ? body : JSON.stringify(body || {}), signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw Object.assign(new Error(result.error || 'Could not complete that scan.'), {status:response.status});
      return result;
    } finally {
      clearTimeout(timeout);
      if (requestController === controller) requestController = null;
    }
  }

  function resetResult() {
    latestResult = null;
    $('label').textContent = 'Ready for an item';
    $('result-bin').hidden = true;
    $('score').textContent = '—';
    $('score-bar').value = 0;
    $('candidates').replaceChildren();
    $('hint').textContent = 'Show one item against a plain background.';
    $('use-result').disabled = true;
  }

  function stop(notify = true) {
    running = false;
    generation++;
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    if (requestController) requestController.abort();
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    $('video').srcObject = null;
    $('video').hidden = true;
    $('guide').hidden = true;
    if ($('preview').dataset.streaming) {
      $('preview').removeAttribute('src');
      delete $('preview').dataset.streaming;
      $('preview').hidden = true;
    }
    $('placeholder').hidden = !$('preview').hidden;
    $('stop').hidden = true;
    $('start').hidden = $('source').value === 'upload';
    $('start').disabled = !ready || !signedIn;
    if (owned && notify) {
      fetch('/api/classifier/stop', {method:'POST', keepalive:true,
        headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf}, body:JSON.stringify({generation:cameraGeneration})}).catch(() => {});
    }
    owned = false;
    cameraGeneration = null;
  }

  function sourceChanged() {
    stop(); resetResult(); message('');
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    $('preview').removeAttribute('src');
    $('preview').hidden = true;
    $('placeholder').hidden = false;
    $('upload-label').hidden = $('source').value !== 'upload';
    $('start').textContent = $('source').value === 'server' ? 'Start detection' : 'Start camera';
  }

  function show(result) {
    const checking = result.state === 'checking';
    const recognized = !checking && ['Trash','Recyclable'].includes(result.category) && !result.drop_off && result.scan_id;
    latestResult = recognized ? result : null;
    const label = checking ? 'Checking item…' : result.label;
    if ($('label').textContent !== label) $('label').textContent = label;
    $('result-bin').hidden = !result.category || checking;
    $('result-bin').textContent = result.drop_off ? 'Special drop-off' : result.category === 'Recyclable' ? 'Recycling · +10 points per item' : 'Trash · tracked, 0 points';
    $('result-bin').classList.toggle('is-recycling', result.category === 'Recyclable');
    const hint = checking ? `Hold still — comparing readings (${result.checks}/${result.of}).`
      : result.drop_off ? 'Take this item to a drop-off site. It does not belong in the regular bin.'
      : recognized ? 'Check the result, then use it to confirm your drop below.'
      : 'No supported item found. Try another angle or enter your item below.';
    if ($('hint').textContent !== hint) $('hint').textContent = hint;
    const score = Math.max(0,Math.min(1,Number(result.score) || 0));
    $('score').textContent = Math.round(score*100)+'%';
    $('score-bar').value = score;
    $('candidates').replaceChildren(...(result.alternatives || []).map(item => {
      const li = document.createElement('li'), value = document.createElement('span');
      li.textContent = item.label;
      value.textContent = Math.round(item.score*100)+'%';
      li.append(value);
      return li;
    }));
    $('timing').textContent = `Last recognition: ${Number(result.seconds || 0).toFixed(2)}s · Processed locally`;
    $('use-result').disabled = !recognized;
  }

  async function frameBlob() {
    const video = $('video');
    if (!video.videoWidth || !video.videoHeight) throw new Error('The camera is not supplying frames yet.');
    const scale = Math.min(1,640/Math.max(video.videoWidth,video.videoHeight));
    canvas.width = Math.round(video.videoWidth*scale);
    canvas.height = Math.round(video.videoHeight*scale);
    canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/jpeg',.85));
    if (!blob) throw new Error('Could not capture a camera frame.');
    return blob;
  }

  async function loop(token) {
    while (running && generation === token) {
      try {
        const serverCamera = $('source').value === 'server';
        const body = serverCamera ? {} : await frameBlob();
        if (!running || generation !== token) return;
        const result = await request(serverCamera ? '/api/classifier/camera' : '/api/classifier/predict',body,true,true);
        if (!running || generation !== token) return;
        show(result); message('');
      } catch (error) {
        if (generation !== token) return;
        if (error.status !== 429) { stop(); message(error.name === 'AbortError' ? 'Scanning timed out. Start again or try a photo.' : error.message,true); return; }
      }
      await new Promise(resolve => setTimeout(resolve,350));
    }
  }

  $('start').addEventListener('click',async () => {
    if (!signedIn || !ready) return;
    message(''); $('start').disabled = true;
    const token = ++generation;
    try {
      const source = $('source').value;
      if (source === 'browser') {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS. Use the connected camera or upload a photo on a plain network address.');
        const acquired = await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:640}},audio:false});
        if (generation !== token) { acquired.getTracks().forEach(track=>track.stop()); return; }
        stream = acquired;
        $('video').classList.toggle('mirrored',acquired.getVideoTracks()[0].getSettings().facingMode !== 'environment');
        $('video').srcObject = stream;
        await $('video').play();
        if (generation !== token) return;
      }
      const result = await request('/api/classifier/start',{source});
      if (generation !== token) {
        request('/api/classifier/stop',{generation:result.generation}).catch(()=>{});
        return;
      }
      owned = true; cameraGeneration = result.generation;
      if (source === 'server') {
        $('preview').dataset.streaming = 'true';
        $('preview').src = result.url;
        $('preview').hidden = false; $('video').hidden = true;
      } else {
        $('video').hidden = false; $('preview').hidden = true; $('guide').hidden = false;
      }
      $('placeholder').hidden = true;
      running = true; sizeGuide(); resetResult(); $('start').hidden = true; $('stop').hidden = false;
      let pulsing = false;
      heartbeatTimer = setInterval(async () => {
        if (!running || pulsing) return;
        pulsing = true;
        try { await request('/api/classifier/heartbeat',{generation:cameraGeneration}); }
        catch(error) { if (generation === token) { stop(); message(error.message,true); } }
        finally { pulsing = false; }
      },700);
      loop(token);
    } catch(error) {
      if (generation === token) { stop(); message(error.message,true); }
    }
  });

  $('stop').addEventListener('click',()=>stop());
  $('source').addEventListener('change',sourceChanged);
  $('file').addEventListener('change',async event => {
    const file = event.target.files[0];
    if (!file) return;
    if (!ready || !signedIn) { message('Wait for the scanner to be ready.',true); event.target.value=''; return; }
    stop(); resetResult(); const token = generation;
    if (file.size > 8*1024*1024) { message('Choose an image smaller than 8 MB.',true); event.target.value=''; return; }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    $('preview').src = objectUrl;
    $('preview').hidden = false; $('placeholder').hidden = true;
    message('Recognizing your item…');
    try {
      const result = await request('/api/classifier/predict',file,false,true);
      if (token === generation) { show(result); message(''); }
    } catch(error) { if(token === generation) message(error.name === 'AbortError' ? 'Recognition timed out. Try another photo.' : error.message,true); }
    event.target.value='';
  });

  $('use-result').addEventListener('click',()=> {
    if (!latestResult) return;
    const result = {...latestResult};
    stop();
    document.dispatchEvent(new CustomEvent('trash:recognized',{detail:result}));
    message('Recognized item added to your drop. Confirm it below.');
  });

  $('model-load').addEventListener('click',async () => {
    $('model-load').disabled = true;
    try { await request('/api/classifier/load',{}); message('Preparing the scanner. You can still record items manually.'); }
    catch(error) { message(error.message,true); }
    finally { $('model-load').disabled = false; }
  });

  async function status() {
    try {
      const response = await fetch('/api/classifier/status');
      const result = await response.json();
      ready = result.ready;
      $('detector-status').textContent = result.busy ? 'Scanner in use' : result.ready ? 'Scanner ready' : result.loading ? 'Preparing scanner…' : result.error ? 'Scanner unavailable' : 'Scanner on standby';
      $('detector-dot').classList.toggle('ready',ready);
      $('model-load').hidden = !signedIn || ready || result.loading;
      $('model-load').textContent = result.error ? 'Retry scanner' : 'Prepare scanner';
      $('lid-status').textContent = result.lid_enabled ? 'Live scanning opens the matching bin lid' : 'Bin lids are controlled manually';
      if (!running) $('start').disabled = !ready || !signedIn || result.busy;
      $('file').disabled = !ready || !signedIn;
      if (result.error && signedIn) message('The scanner could not load. Retry it or record your item manually.',true);
    } catch (_) { $('detector-status').textContent = 'Connecting to scanner…'; }
    statusTimer = setTimeout(status,2000);
  }
  window.addEventListener('resize',sizeGuide);
  window.addEventListener('pagehide',()=> { stop(); clearTimeout(statusTimer); if(objectUrl) URL.revokeObjectURL(objectUrl); });
  document.addEventListener('visibilitychange',()=> { if(document.hidden) stop(); });
  status();
})();

if ($("#connect-button") && signedIn) {
  const commands = {w:"w", a:"a", s:"s", d:"d", ArrowUp:"w", ArrowLeft:"a", ArrowDown:"s", ArrowRight:"d"};
  const labels = {w:"MOVING FORWARD", s:"MOVING BACKWARD", a:"SPINNING LEFT", d:"SPINNING RIGHT", x:"STOPPED"};
  let status = {connected:false, owned:false, mode:"manual", command:"x"};
  let heldCommand = null;
  let heldKey = null;
  let sendTimer;
  let sending = false;
  let leaving = false;
  let changingMode = false;
  let sequence = 0;

  function feedback(message, error = false) {
    $("#rover-feedback").textContent = message;
    $("#rover-feedback").classList.toggle("error", error);
  }

  function showStatus(next) {
    // Ignore responses captured before a newer STOP or mode change.
    if (next.epoch !== undefined && status.epoch !== undefined && next.epoch < status.epoch) return;
    if (next.epoch === status.epoch && next.sequence < status.sequence) return;
    sequence = Math.max(sequence, next.sequence || 0);
    status = next;
    const owned = next.connected && next.owned;
    const badge = $("#connection-badge");
    badge.textContent = next.busy ? "ANOTHER PILOT IS DRIVING" : owned ? (next.link === "wifi" ? "WI-FI TARGET SET" : "BLUETOOTH LINK OPEN") : "ROVER OFFLINE";
    badge.classList.toggle("online", owned);
    $("#connect-button").textContent = owned ? "Disconnect" : "Connect rover";
    $("#connect-button").disabled = next.busy || changingMode;
    $("#transport").disabled = next.connected;
    document.querySelectorAll(".drive-button, [data-mode], #emergency-stop").forEach((button) => { button.disabled = !owned || changingMode; });
    $("#connection-note").textContent = next.busy ? "The current pilot must disconnect before you can take control." : owned && next.link === "wifi" ? "Commands target the configured Pi. UDP does not confirm delivery." : owned ? "Bluetooth serial link is open. Keep the rover in view." : "Run this website on the laptop paired with the Pi.";
    $("#motion-state").textContent = owned ? (labels[next.command] || `HAND ANGLE ${next.command}°`) : "STANDING BY";
    $("#active-mode").textContent = (next.mode || "manual").toUpperCase();
    document.querySelectorAll("[data-mode-card]").forEach((card) => card.classList.toggle("selected-mode", owned && card.dataset.modeCard === next.mode));
    $("#voice-status").textContent = next.voice_error ? "Voice session ended. Enable it again to retry." : next.mode === "voice" ? (next.voice_ready ? "Listening on the laptop. Say a direction or “stop.”" : "Starting the voice session…") : "Microphone activates only when enabled.";
    const camera = $("#camera-panel");
    const cameraActive = owned && next.mode === "gesture";
    if (cameraActive && camera.hidden) $("#camera-view").src = "/api/rover/camera";
    if (!cameraActive && !camera.hidden) $("#camera-view").removeAttribute("src");
    camera.hidden = !cameraActive;
    if (!owned) clearHeld();
    if (next.error) feedback(next.error, true);
    else if (next.camera_error) feedback(next.camera_error, true);
  }

  function clearHeld() {
    heldCommand = null;
    heldKey = null;
    clearInterval(sendTimer);
    document.querySelectorAll(".drive-button").forEach((button) => button.classList.remove("pressed"));
  }

  async function sendHeld() {
    if (!heldCommand || sending || !status.owned) return;
    sending = true;
    try { showStatus(await api("/api/rover/command", {command:heldCommand, epoch:status.epoch, sequence:++sequence})); }
    catch (error) { clearHeld(); feedback(error.message, true); }
    finally { sending = false; }
  }

  function begin(command, key = null) {
    if (!status.owned || changingMode) return;
    clearHeld();
    heldCommand = command;
    heldKey = key;
    const button = document.querySelector(`[data-command="${command}"]`);
    if (button) button.classList.add("pressed");
    sendHeld();
    sendTimer = setInterval(sendHeld, 160);
  }

  async function release() {
    if (!heldCommand) return;
    clearHeld();
    if (!status.owned) return;
    try { showStatus(await api("/api/rover/command", {command:"x", epoch:status.epoch, sequence:++sequence})); }
    catch (error) { feedback(error.message, true); }
  }

  async function stopAll() {
    clearHeld();
    if (!status.owned) return;
    try { showStatus(await api("/api/rover/stop", {})); feedback("Rover stopped. Assisted controls are off."); }
    catch (error) { feedback(error.message, true); }
  }

  $("#connect-button").addEventListener("click", async () => {
    const disconnecting = status.owned;
    const button = $("#connect-button");
    button.disabled = true;
    button.textContent = disconnecting ? "Disconnecting…" : "Connecting…";
    if (!disconnecting && $("#transport").value === "bluetooth") feedback("Opening the Bluetooth link. The first connection can take a few seconds.");
    clearHeld();
    try {
      // Opening a Bluetooth serial port can take several seconds on Windows.
      showStatus(await api("/api/rover/" + (disconnecting ? "disconnect" : "connect"), {transport:$("#transport").value}, disconnecting ? 5000 : 20000));
      feedback(disconnecting ? "Rover stopped and disconnected." : "Ready. Hold a direction to drive.");
    } catch (error) {
      feedback(error.message, true);
      showStatus(status);
    }
  });

  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", async () => {
    changingMode = true;
    clearHeld();
    showStatus(status);
    feedback("Starting " + button.dataset.mode + " controls…");
    try { showStatus(await api("/api/rover/mode", {mode:button.dataset.mode})); feedback("Control mode updated. Manual input always has priority."); }
    catch (error) { feedback(error.message, true); }
    finally {
      changingMode = false;
      try { showStatus(await api("/api/rover")); } catch (_) { showStatus(status); }
    }
  }));

  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      begin(button.dataset.command);
    });
    button.addEventListener("pointerup", release);
    button.addEventListener("pointercancel", release);
    button.addEventListener("lostpointercapture", release);
    button.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && !event.repeat) { event.preventDefault(); begin(button.dataset.command); }
    });
    button.addEventListener("keyup", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); release(); }
    });
    button.addEventListener("blur", release);
  });

  $("#emergency-stop").addEventListener("click", stopAll);
  $("#center-stop").addEventListener("click", stopAll);
  document.addEventListener("keydown", (event) => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName) || event.target.isContentEditable) return;
    if (!status.owned || changingMode) return;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (event.key === "Escape" || (event.key === " " && !event.target.matches("[data-command]"))) { event.preventDefault(); if (!event.repeat) stopAll(); }
    else if (commands[key]) { event.preventDefault(); if (!event.repeat) begin(commands[key], key); }
  });
  document.addEventListener("keyup", (event) => {
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (key === heldKey) { event.preventDefault(); release(); }
  });

  function leave() {
    clearHeld();
    leaving = true;
    if (status.owned) {
      fetch("/api/rover/disconnect", {method:"POST", keepalive:true, headers:{"Content-Type":"application/json", "X-CSRF-Token":csrf}, body:"{}"}).catch(() => {});
      showStatus({...status, owned:false, connected:false});
    }
  }
  // Losing focus can swallow a key release, so stop the rover but stay connected.
  window.addEventListener("blur", () => { if (heldCommand) release(); });
  try { const saved = localStorage.getItem("rover-transport"); if (saved) $("#transport").value = saved; } catch (_) {}
  $("#transport").addEventListener("change", () => { try { localStorage.setItem("rover-transport", $("#transport").value); } catch (_) {} });
  window.addEventListener("pagehide", leave);
  document.addEventListener("visibilitychange", () => { if (document.hidden) leave(); else leaving = false; });
  window.addEventListener("focus", () => { leaving = false; });

  async function tick() {
    try {
      if (!leaving && !document.hidden) {
        if (status.owned) await api("/api/rover/heartbeat", {});
        showStatus(await api("/api/rover"));
      }
    } catch (error) {
      clearHeld();
      showStatus({...status, connected:false, owned:false});
      feedback(error.message, true);
    } finally { setTimeout(tick, 350); }
  }
  tick();
}

})();
