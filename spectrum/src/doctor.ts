import { loadConfig } from './config.js';
import { bridgeRequest, BridgeError } from './bridge.js';
import { cloud, SpectrumCloudError } from '@spectrum-ts/core';
import { telegramIdentity } from './cloud.js';

async function main() {
  const terminal = process.argv.includes('--terminal');
  let config;
  try { config = loadConfig(terminal); }
  catch (error) { console.error((error as Error).message); process.exitCode = 1; return; }
  console.log('Local configuration: ready (credentials hidden).');
  try {
    // Check the private bridge without claiming a Spectrum transport is connected.
    await bridgeRequest(config, '/api/integrations/spectrum/message', {
      platform: 'terminal', space_id: 'doctor', sender_id: 'doctor',
      message_id: 'doctor-health-check', text: 'help', is_group: false,
    });
    console.log('Authenticated dashboard bridge: ready.');
  } catch (error) {
    console.error(error instanceof BridgeError && error.status === 401
      ? 'Dashboard rejected the bridge key. Restart Python after editing BRH_Test/.env.'
      : 'Dashboard unavailable. Start the dashboard at SPECTRUM_BACKEND_URL.');
    process.exitCode = 1;
  }
  console.log(`Selected provider: ${config.provider}.`);
  if (config.provider === 'telegram' && !config.allowedSenders.telegram.size) console.log('Telegram onboarding mode: only private /start and /whoami are available until you add your numeric user ID to SPECTRUM_TELEGRAM_ALLOWED_SENDERS.');
  if (process.argv.includes('--cloud') && !terminal) {
    const watchdog = setTimeout(() => { console.error('Photon account check timed out.'); process.exit(1); }, 20000);
    try {
      await cloud.getProject(config.projectId!, config.projectSecret!);
      console.log('Photon project authentication: ready.');
      if (config.provider === 'telegram') {
        const username = await telegramIdentity(config.telegramBotToken!);
        await cloud.issueFusorToken(config.projectId!, config.projectSecret!);
        console.log(`Telegram bot verified: https://t.me/${username}. Photon Fusor authentication: ready.`);
        console.log('Start the worker to register the Telegram webhook, then send /start to your bot.');
        return;
      }
      const token = await cloud.issueImessageTokens(config.projectId!, config.projectSecret!);
      if (token.type === 'dedicated') {
        const numbers = Object.values(token.numbers).filter(Boolean);
        console.log(`Photon managed lines assigned: ${numbers.length}.`);
        for (const number of numbers) console.log(`Agent iMessage number: ${number}`);
        if (!numbers.length) process.exitCode = 1;
      } else console.log('Photon shared iMessage transport: authenticated.');
    } catch (error) {
      console.error(error instanceof SpectrumCloudError
        ? `Photon rejected the account check (${error.status}, ${error.code}). Check project Settings and line setup.`
        : 'Could not reach Photon for the account check.');
      process.exitCode = 1;
    } finally { clearTimeout(watchdog); }
  }
}
void main();
