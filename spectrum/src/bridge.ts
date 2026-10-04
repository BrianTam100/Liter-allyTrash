import type { Config } from './config.js';

export class BridgeError extends Error {
  constructor(public status: number) { super(`Dashboard request failed (${status}).`); }
}

export async function bridgeRequest<T>(config: Config, path: string, data: unknown): Promise<T> {
  // Retry ambiguous transport failures using the same message ID. The backend deduplicates writes.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(config.backend + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.bridgeKey}` },
        body: JSON.stringify(data), signal: AbortSignal.timeout(25000), redirect: 'error',
      });
      if (!response.ok) throw new BridgeError(response.status);
      return await response.json() as T;
    } catch (error) {
      if (error instanceof BridgeError && error.status < 500) throw error;
      if (attempt === 2) throw error;
      await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)));
    }
  }
  throw new Error('Dashboard unavailable.');
}
