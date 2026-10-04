import { cloud } from '@spectrum-ts/core';
import type { Config } from './config.js';

export async function telegramIdentity(token: string): Promise<string> {
  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/getMe`, { signal: AbortSignal.timeout(10000), redirect: 'error' });
    const body = await response.json() as { ok: boolean; result?: { username?: string } };
    if (!response.ok || !body.ok || !body.result?.username) throw new Error();
    return body.result.username;
  } catch {
    // Fetch errors can contain the secret embedded in the Bot API URL.
    throw new Error('Telegram bot verification failed. Check the BotFather token and network connection.');
  }
}

export async function checkCloud(config: Config) {
  await cloud.getProject(config.projectId!, config.projectSecret!);
  if (config.provider === 'telegram') {
    const telegramUsername = await telegramIdentity(config.telegramBotToken!);
    await cloud.issueFusorToken(config.projectId!, config.projectSecret!);
    return { telegramUsername };
  }
  // The SDK's getPlatforms helper omits authentication. Token issuance is the
  // authenticated readiness check for the provider we actually use.
  const tokens = await cloud.issueImessageTokens(config.projectId!, config.projectSecret!);
  if (tokens.type === 'dedicated' && !Object.values(tokens.numbers).some(Boolean)) {
    throw new Error('No managed iMessage line is assigned to this Photon project.');
  }
  return { telegramUsername: undefined };
}
