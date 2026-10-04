(() => {
  'use strict';
  const form = document.querySelector('#gemini-form');
  if (!form) return;
  const photo = form.querySelector('#gemini-photo');
  const description = form.querySelector('#gemini-description');
  const preview = form.querySelector('#gemini-preview');
  const remove = form.querySelector('#gemini-remove');
  const feedback = form.querySelector('#gemini-feedback');
  const result = document.querySelector('#gemini-result');
  const empty = document.querySelector('#gemini-empty');
  const note = document.querySelector('#gemini-result-note');
  const reset = document.querySelector('#gemini-reset');
  const panel = document.querySelector('#gemini-result-panel');
  let previewURL = null;
  let busy = false;
  function showAnswer(answer) {
    result.replaceChildren();
    const headings = new Set(['what i can tell', 'best next step', 'before disposal', 'reuse option', 'what to verify']);
    for (const line of answer.split('\n').map(value => value.replace(/\*\*/g, '').trim()).filter(Boolean)) {
      const heading = line.replace(/^#+\s*/, '').replace(/:$/, '');
      const element = document.createElement(headings.has(heading.toLowerCase()) ? 'h3' : 'p');
      element.textContent = element.tagName === 'H3' ? heading : line.replace(/^[*-]\s+/, '• ');
      result.append(element);
    }
  }
  function clearPhoto() {
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null;
    photo.value = '';
    preview.removeAttribute('src');
    preview.hidden = remove.hidden = true;
  }
  photo.addEventListener('change', () => {
    const file = photo.files[0];
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null;
    preview.hidden = remove.hidden = true;
    feedback.textContent = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      clearPhoto();
      feedback.textContent = 'Choose a JPEG, PNG, or WebP photo smaller than 5 MB.';
      return;
    }
    previewURL = URL.createObjectURL(file);
    preview.src = previewURL;
    preview.hidden = remove.hidden = false;
  });
  remove.addEventListener('click', clearPhoto);
  form.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    description.value = button.dataset.example;
    description.focus();
  }));
  reset.addEventListener('click', () => {
    form.reset();
    clearPhoto();
    result.textContent = feedback.textContent = '';
    result.hidden = note.hidden = reset.hidden = true;
    empty.hidden = false;
    description.focus();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (!description.value.trim() && !photo.files.length) {
      feedback.textContent = 'Describe an item or choose a photo first.';
      description.focus();
      return;
    }
    const data = new FormData(form);
    if (!photo.files.length) data.delete('photo');
    busy = true;
    const controls = [...form.querySelectorAll('input, textarea, button'), reset];
    controls.forEach(control => { control.disabled = true; });
    panel.setAttribute('aria-busy', 'true');
    result.hidden = note.hidden = reset.hidden = true;
    empty.hidden = false;
    feedback.textContent = 'Gemini is examining your item and preparing a plan…';
    try {
      const response = await fetch('/api/gemini/analyze', {
        method: 'POST', body: data,
        headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content},
        signal: AbortSignal.timeout(30000),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Analysis is unavailable. Try again shortly.');
      showAnswer(body.answer);
      empty.hidden = true;
      result.hidden = note.hidden = reset.hidden = false;
      feedback.textContent = 'Your sorting plan is ready.';
      result.focus();
    } catch (error) {
      feedback.textContent = error.name === 'TimeoutError' || error instanceof TypeError
        ? 'The connection took too long. Your input is still here; try again.' : error.message;
    } finally {
      busy = false;
      controls.forEach(control => { control.disabled = false; });
      panel.setAttribute('aria-busy', 'false');
    }
  });
  window.addEventListener('pagehide', () => { if (previewURL) URL.revokeObjectURL(previewURL); });
})();
