import { config as dotenv } from "dotenv";
import { fileURLToPath } from "node:url";
import { createHash } from 'node:crypto';

dotenv({ path: fileURLToPath(new URL("../../BRH_Test/.env", import.meta.url)) });

export function loadConfig(terminalOnly = false, env: NodeJS.ProcessEnv = process.env) {
  const provider = terminalOnly ? 'terminal' : (env.SPECTRUM_PROVIDER?.trim() || 'imessage');
  if (!['imessage', 'telegram', 'terminal'].includes(provider)) throw new Error('SPECTRUM_PROVIDER must be imessage or telegram.');
  const backend = new URL(env.SPECTRUM_BACKEND_URL || "http://127.0.0.1:8000");
  if (!['http:', 'https:'].includes(backend.protocol) || backend.username || backend.password) {
    throw new Error("SPECTRUM_BACKEND_URL must be an HTTP(S) URL without embedded credentials.");
  }
  if (backend.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(backend.hostname)) {
    throw new Error("Use HTTPS for a remote backend so the bridge key stays private.");
  }
  const bridgeKey = env.SPECTRUM_BRIDGE_KEY?.trim();
  if (!bridgeKey) throw new Error("Set SPECTRUM_BRIDGE_KEY in BRH_Test/.env, then restart the dashboard.");
  const projectId = env.SPECTRUM_PROJECT_ID?.trim();
  const projectSecret = env.SPECTRUM_PROJECT_SECRET?.trim();
  if (provider !== 'terminal' && (!projectId || !projectSecret)) {
    throw new Error("Set SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET from Photon project Settings.");
  }
  const parseList = (value = '') => new Set(value.split(',').map(s => s.trim()).filter(Boolean));
  const allowedSenders = {
    imessage: parseList(env.SPECTRUM_ALLOWED_SENDERS),
    telegram: parseList(env.SPECTRUM_TELEGRAM_ALLOWED_SENDERS),
  };
  if (provider === 'imessage' && !allowedSenders.imessage.size) throw new Error("Set SPECTRUM_ALLOWED_SENDERS to the phone numbers or Apple IDs allowed to use this pilot.");
  if ([...allowedSenders.telegram].some(id => !/^[1-9]\d*$/.test(id))) throw new Error('SPECTRUM_TELEGRAM_ALLOWED_SENDERS must contain numeric user IDs, not phone numbers or usernames.');
  const telegramBotToken = env.SPECTRUM_TELEGRAM_BOT_TOKEN?.trim();
  if (provider === 'telegram' && (!telegramBotToken || !/^\d+:[A-Za-z0-9_-]+$/.test(telegramBotToken))) {
    throw new Error('Create a bot with @BotFather and set SPECTRUM_TELEGRAM_BOT_TOKEN in BRH_Test/.env.');
  }
  const telegramWebhookSecret = env.SPECTRUM_TELEGRAM_WEBHOOK_SECRET?.trim()
    || createHash('sha256').update('sortrover-telegram:' + bridgeKey).digest('hex');
  if (provider === 'telegram' && !/^[A-Za-z0-9_-]{1,256}$/.test(telegramWebhookSecret)) throw new Error('Invalid Telegram webhook secret format.');
  return { backend: backend.origin, bridgeKey, projectId, projectSecret, allowedSenders, provider, telegramBotToken, telegramWebhookSecret };
}

export type Config = ReturnType<typeof loadConfig>;
