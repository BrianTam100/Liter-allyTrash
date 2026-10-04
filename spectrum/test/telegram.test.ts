import test from 'node:test';
import assert from 'node:assert/strict';
import { makeHandler, type Envelope, type Incoming, type Space } from '../src/handler.js';
import { loadConfig } from '../src/config.js';

function fixture(authorized = true) {
  const sent: string[] = [], forwarded: Envelope[] = [];
  const space: Space = {id:'12345',send:async text => {sent.push(text);},responding:async fn => fn()};
  const message: Incoming = {id:'42',platform:'telegram',direction:'inbound',timestamp:new Date(),
    sender:{id:'12345'},content:{type:'text',text:'progress'}};
  const handler = makeHandler({imessage:new Set(['12345']),telegram:new Set(authorized ? ['12345'] : [])},
    async payload => {forwarded.push(payload); return {reply:'Progress ready'};}, Date.now, 'SortRoverBot');
  return {sent,forwarded,space,message,handler};
}

test('Telegram DMs reach the existing bridge with isolated identity and replay protection', async () => {
  const f=fixture();
  await f.handler(f.space,f.message); await f.handler(f.space,f.message);
  assert.equal(f.forwarded.length,1);
  assert.equal(f.forwarded[0].platform,'telegram');
  assert.equal(f.forwarded[0].is_group,false);
});
test('unapproved users can obtain their ID without reading or writing Pilot data', async () => {
  const f=fixture(false);
  await f.handler(f.space,f.message);
  assert.equal(f.sent.length,0);
  await f.handler(f.space,{...f.message,content:{type:'text',text:'/start'}});
  assert.match(f.sent[0],/12345/);
  assert.equal(f.forwarded.length,0);
});
test('negative Telegram group IDs require addressing and target the correct bot', async () => {
  const f=fixture(); f.space.id='-100987654321';
  await f.handler(f.space,f.message);
  await f.handler(f.space,{...f.message,content:{type:'text',text:'/rover@SomeoneElseBot progress'}});
  assert.equal(f.forwarded.length,0);
  await f.handler(f.space,{...f.message,content:{type:'text',text:'/rover@SortRoverBot progress'}});
  assert.equal(f.forwarded[0].is_group,true);
  assert.equal(f.forwarded[0].text,'Rover, progress');
});
test('setup commands never reveal identities in groups', async () => {
  const f=fixture(false); f.space.id='-999';
  await f.handler(f.space,{...f.message,content:{type:'text',text:'/whoami'}});
  assert.equal(f.sent.length,0); assert.equal(f.forwarded.length,0);
});
test('authorized start becomes help and whoami stays private', async () => {
  const f=fixture();
  await f.handler(f.space,{...f.message,content:{type:'text',text:'/start'}});
  assert.equal(f.forwarded[0].text,'help');
  await f.handler(f.space,{...f.message,id:'43',content:{type:'text',text:'/whoami'}});
  assert.equal(f.forwarded.length,1);
  assert.match(f.sent[1],/12345/);
});
test('Telegram configuration allows onboarding but validates bot tokens and numeric allowlists', () => {
  const env={SPECTRUM_PROVIDER:'telegram',SPECTRUM_PROJECT_ID:'project',SPECTRUM_PROJECT_SECRET:'secret',
    SPECTRUM_BRIDGE_KEY:'bridge',SPECTRUM_TELEGRAM_BOT_TOKEN:'123456:TEST_TOKEN'};
  const c=loadConfig(false,env);
  assert.equal(c.provider,'telegram'); assert.equal(c.allowedSenders.telegram.size,0);
  assert.match(c.telegramWebhookSecret,/^[a-f0-9]{64}$/);
  assert.equal(c.telegramWebhookSecret,loadConfig(false,env).telegramWebhookSecret);
  assert.throws(()=>loadConfig(false,{...env,SPECTRUM_TELEGRAM_BOT_TOKEN:''}),/BotFather/);
  assert.throws(()=>loadConfig(false,{...env,SPECTRUM_TELEGRAM_ALLOWED_SENDERS:'@user'}),/numeric user IDs/);
});
