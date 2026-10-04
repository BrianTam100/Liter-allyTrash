import test from 'node:test';
import assert from 'node:assert/strict';
import { makeHandler, type Incoming, type Space } from '../src/handler.js';

function fixture() {
  const sent: string[] = [], received: unknown[] = [];
  const space: Space = {id: 'chat', type:'dm', send:async text => { sent.push(text); }, responding:async fn => fn()};
  const message: Incoming = {id:'inbound', platform:'imessage', direction:'inbound', timestamp:new Date(),
    sender:{id:'+15551111111'}, content:{type:'text',text:'progress'}};
  const handler = makeHandler({imessage:new Set(['+15551111111']), telegram:new Set(['12345'])}, async payload => {received.push(payload); return {reply:'20 points'};});
  return {sent, received, space, message, handler};
}

test('forwards inbound messages and suppresses delivered replays', async () => {
  const f = fixture();
  await f.handler(f.space, f.message);
  await f.handler(f.space, f.message);
  assert.equal(f.received.length, 1);
  assert.deepEqual(f.sent, ['20 points']);
});
test('ignores outbound, unauthorized, stale, and attachment events', async () => {
  const f = fixture();
  await f.handler(f.space, {...f.message, direction:'outbound'});
  await f.handler(f.space, {...f.message, sender:{id:'stranger'}});
  await f.handler(f.space, {...f.message, timestamp:new Date(Date.now()-600000)});
  await f.handler(f.space, {...f.message, content:{type:'attachment'}});
  assert.equal(f.received.length, 0);
});
test('group conversations respond only when addressed', async () => {
  const f = fixture(); f.space.type = 'group';
  await f.handler(f.space, f.message);
  assert.equal(f.received.length, 0);
  await f.handler(f.space, {...f.message, content:{type:'text', text:'Rover, progress'}});
  assert.equal(f.received.length, 1);
});
test('threaded text replies are forwarded', async () => {
  const f = fixture();
  await f.handler(f.space, {...f.message, content:{type:'reply', content:{type:'text', text:'confirm ABCDEF'}}});
  assert.equal(f.received.length, 1);
});
test('backend failure gives a fallback and permits retry', async () => {
  const f = fixture(); let fail = true;
  const handler = makeHandler({imessage:new Set(['+15551111111']), telegram:new Set(['12345'])}, async () => {
    if (fail) throw new Error('offline'); return {reply:'ready'};
  });
  await handler(f.space, f.message);
  assert.match(f.sent[0], /temporarily unavailable/);
  fail = false;
  await handler(f.space, f.message);
  assert.equal(f.sent[1], 'ready');
});
