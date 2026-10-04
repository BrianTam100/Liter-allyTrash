(() => {
  'use strict';
  const form = document.querySelector('#companion-form');
  if (!form) return;
  const transcript = document.querySelector('#companion-transcript');
  const input = document.querySelector('#companion-input');
  const button = form.querySelector('button');
  const feedback = document.querySelector('#companion-feedback');
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let retry = null;
  let busy = false;

  function append(role, text) {
    const row = document.createElement('p');
    row.className = 'companion-message ' + role;
    const label = document.createElement('strong');
    label.textContent = role === 'user' ? 'You: ' : 'Rover: ';
    row.append(label, document.createTextNode(text));
    transcript.append(row);
    transcript.scrollTop = transcript.scrollHeight;
  }

  async function request(path, data) {
    const response = await fetch(path, {
      method: data ? 'POST' : 'GET',
      headers: {'Content-Type':'application/json', 'X-CSRF-Token':csrf},
      body: data ? JSON.stringify(data) : undefined,
      signal: AbortSignal.timeout(25000),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The companion is unavailable.');
    return result;
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true;
    input.disabled = button.disabled = true;
    feedback.textContent = 'Rover is thinking…';
    if (!retry || retry.text !== text) {
      retry = {text, message_id:crypto.randomUUID()};
      append('user', text);
    }
    try {
      const result = await request('/api/companion/message', retry);
      if (text.toLowerCase() === 'forget') transcript.replaceChildren();
      if (result.reply) append('assistant', result.reply);
      retry = null;
      input.value = '';
      feedback.textContent = '';
      // Confirmed chat drops are reflected in the same dashboard records.
      if (/^confirm\s/i.test(text)) {
        const response = await fetch('/');
        if (response.ok) {
          const fresh = new DOMParser().parseFromString(await response.text(), 'text/html');
          for (const name of ['points','recycled','items','collections']) {
            const current = document.querySelector('#stat-' + name), next = fresh.querySelector('#stat-' + name);
            if (current && next) current.textContent = next.textContent;
          }
          const history = document.querySelector('.history-panel'), next = fresh.querySelector('.history-panel');
          if (history && next) history.replaceWith(next);
        }
      }
    } catch (error) {
      feedback.textContent = error.name === 'TimeoutError' || error instanceof TypeError
        ? 'Connection interrupted. Send again to retry safely.' : error.message;
    } finally {
      busy = false;
      input.disabled = button.disabled = false;
      input.focus();
    }
  });

  request('/api/companion/history').then(result => {
    if (!result.messages.length) append('assistant', "I'm Rover. Ask about your progress or where an item belongs. To record a drop, try ‘log 2 plastic bottles in recycling’.");
    else result.messages.forEach(message => append(message.role, message.content));
  }).catch(() => { feedback.textContent = 'Could not load conversation history. You can still send a message.'; });

  async function status() {
    try {
      const result = await request('/api/companion/status');
      const label = document.querySelector('#spectrum-status');
      const names = {imessage:'iMessage', telegram:'Telegram', terminal:'Terminal'};
      label.textContent = result.connected
        ? result.providers.map(provider => names[provider] || provider).join(' / ') + ' agent running'
        : (names[result.selected_provider] || 'Spectrum') + (result.configured ? ' offline' : ' setup needed');
    } catch { document.querySelector('#spectrum-status').textContent = 'Connection unavailable'; }
  }
  void status();
  setInterval(() => { if (!document.hidden) void status(); }, 15000);
})();
