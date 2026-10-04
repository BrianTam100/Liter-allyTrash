// Run with: node --test test_rover_controls.cjs
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");

test("strafe keys and buttons send commands, renew holds, and stop on release", async () => {
  function element(dataset = {}) {
    const classes = new Set();
    return {dataset, hidden:true, tagName:"BODY", listeners:{},
      classList:{add:value => classes.add(value), remove:value => classes.delete(value),
        toggle:() => {}, contains:value => classes.has(value)},
      addEventListener(name, callback) { this.listeners[name] = callback; },
      matches:() => false, setPointerCapture:() => {}, removeAttribute:() => {}};
  }
  const ids = new Map();
  for (const id of ["connect-button", "rover-feedback", "connection-badge", "transport",
    "connection-note", "motion-state", "active-mode", "voice-status", "camera-panel",
    "camera-view", "emergency-stop", "center-stop"]) ids.set(id, element());
  const buttons = ["w", "a", "s", "d", "z", "c"].map(command => element({command}));
  const document = element();
  document.body = {dataset:{signedIn:"true"}};
  document.hidden = false;
  document.getElementById = id => ids.get(id) || null;
  document.querySelector = selector => {
    if (selector.startsWith("meta")) return {content:"test-token"};
    if (selector.startsWith("#")) return ids.get(selector.slice(1)) || null;
    const match = selector.match(/^\[data-command="(\w)"\]$/);
    return match ? buttons.find(button => button.dataset.command === match[1]) : null;
  };
  document.querySelectorAll = selector => selector.includes(".drive-button") || selector === "[data-command]" ? buttons : [];
  const payloads = [], intervals = new Map();
  let timerId = 0;
  let status = {connected:true, owned:true, mode:"manual", command:"x", epoch:1, sequence:0};
  const context = {document, window:element(), AbortController,
    setTimeout:() => 0, clearTimeout:() => {},
    setInterval:callback => { intervals.set(++timerId, callback); return timerId; },
    clearInterval:id => intervals.delete(id),
    fetch:async (path, options) => {
      if (path === "/api/rover/command") {
        const payload = JSON.parse(options.body);
        payloads.push(payload);
        status = {...status, ...payload};
      }
      return {ok:true, json:async () => ({...status})};
    }};
  vm.runInNewContext(readFileSync(join(__dirname, "web/app.js"), "utf8"), context);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  function event(key) {
    return {key, target:element(), repeat:false, button:0, pointerId:1, preventDefault:() => {}};
  }

  for (const key of ["z", "c", "Z", "C"]) {
    const command = key.toLowerCase();
    const button = buttons.find(button => button.dataset.command === command);
    document.listeners.keydown(event(key));
    await settle();
    assert.equal(payloads.at(-1).command, command);
    assert.equal(ids.get("motion-state").textContent, command === "z" ? "STRAFING LEFT" : "STRAFING RIGHT");
    assert.ok(button.classList.contains("pressed"));
    const previousSequence = payloads.at(-1).sequence;
    for (const renew of intervals.values()) renew();
    await settle();
    assert.equal(payloads.at(-1).command, command);
    assert.ok(payloads.at(-1).sequence > previousSequence);
    document.listeners.keyup(event(key));
    await settle();
    assert.equal(payloads.at(-1).command, "x");
    assert.equal(intervals.size, 0);
    assert.ok(!button.classList.contains("pressed"));

    button.listeners.pointerdown(event(key));
    await settle();
    assert.equal(payloads.at(-1).command, command);
    button.listeners.pointerup(event(key));
    await settle();
    assert.equal(payloads.at(-1).command, "x");
  }
});
