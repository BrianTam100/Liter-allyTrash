import { Spectrum, SpectrumCloudError } from '@spectrum-ts/core';
import { imessage } from '@spectrum-ts/imessage';
import { terminal } from '@spectrum-ts/terminal';
import { telegram } from '@spectrum-ts/telegram';
import { loadConfig } from './config.js';
import { bridgeRequest } from './bridge.js';
import { makeHandler } from './handler.js';
import { checkCloud } from './cloud.js';

async function main() {
  const terminalOnly = process.argv.includes('--terminal');
  const config = loadConfig(terminalOnly);
  const providers = [config.provider];
  const heartbeat = (state: string) => bridgeRequest(config, '/api/integrations/spectrum/heartbeat', { state, providers });
  // Check the authenticated Python connection before opening Spectrum's subscription.
  await heartbeat('offline');
  let telegramUsername: string | undefined;
  const initialize = async () => {
    if (config.provider !== 'terminal') ({ telegramUsername } = await checkCloud(config));
    if (config.provider === 'telegram') return await Spectrum({
      projectId: config.projectId!, projectSecret: config.projectSecret!,
      providers: [telegram.config({ botToken: config.telegramBotToken!, webhookSecret: config.telegramWebhookSecret })],
      options: { logLevel: 'warn' },
    });
    return config.provider === 'terminal'
      ? await Spectrum({ providers: [terminal.config()], options: { logLevel: 'warn' } })
      : await Spectrum({ projectId: config.projectId!, projectSecret: config.projectSecret!,
                         providers: [imessage.config()], options: { logLevel: 'warn' } });
  };
  const watchdog = setTimeout(() => { console.error('Spectrum startup timed out. Check Photon connectivity.'); process.exit(1); }, 30000);
  const app = await initialize().finally(() => clearTimeout(watchdog));
  const handle = makeHandler(config.allowedSenders,
    payload => bridgeRequest(config, '/api/integrations/spectrum/message', payload), Date.now, telegramUsername);
  await heartbeat('connected');
  const timer = setInterval(() => { void heartbeat('connected').catch(() => console.error('Dashboard heartbeat failed.')); }, 15000);
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    clearInterval(timer);
    await heartbeat('offline').catch(() => {});
    await app.stop();
  };
  process.once('SIGINT', () => { void stop(); });
  process.once('SIGTERM', () => { void stop(); });
  console.log(`SortRover Spectrum connected (${providers.join(', ')}). Waiting for incoming messages.`);
  if (telegramUsername) console.log(`Open https://t.me/${telegramUsername} and send /start. Use /whoami to obtain your allowlist ID.`);
  try {
    for await (const [space, message] of app.messages) {
      await handle(space, message);
    }
  } finally { await stop(); }
}

main().catch((error: unknown) => {
  // Never dump SDK errors containing account data, auth metadata, or request headers.
  if (error instanceof SpectrumCloudError) {
    console.error(`Photon rejected startup (${error.status}, ${error.code}). Check the project credentials and selected provider setup.`);
  } else console.error('Spectrum startup failed. Run npm run doctor and check Photon line setup.');
  process.exitCode = 1;
});
