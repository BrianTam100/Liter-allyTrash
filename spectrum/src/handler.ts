import { BridgeError } from './bridge.js';

export interface Incoming {
  id: string;
  platform: string;
  direction: string;
  sender?: { id: string; kind?: string };
  content: { type: string; text?: string; content?: Incoming['content'] };
  timestamp: Date;
}
export interface Space {
  id: string;
  type?: string;
  send(text: string): Promise<unknown>;
  responding<T>(fn: () => Promise<T>): Promise<T>;
}
export interface Envelope {
  platform: string;
  space_id: string;
  sender_id: string;
  message_id: string;
  text: string;
  is_group: boolean;
}

export type AllowedSenders = { imessage: Set<string>; telegram: Set<string> };

export function makeHandler(allowed: AllowedSenders, request: (payload: Envelope) => Promise<{ reply: string | null }>, now = () => Date.now(), botUsername?: string) {
  const delivered = new Map<string, number>();
  return async (space: Space, message: Incoming) => {
    if (message.direction !== 'inbound' || message.sender?.kind === 'agent') return;
    const sender = message.sender?.id;
    if (!sender || !['imessage', 'telegram', 'terminal'].includes(message.platform)) return;
    // Replayed input from an old subscription must never execute fresh commands.
    if (!Number.isFinite(message.timestamp.getTime()) || now() - message.timestamp.getTime() > 300000) return;
    const content = message.content.type === 'reply' ? message.content.content : message.content;
    if (content?.type !== 'text' || !content.text?.trim()) return;
    // Spectrum Telegram spaces expose chat ID only; Telegram group/channel IDs are negative.
    const isGroup = space.type === 'group' || (message.platform === 'telegram' && space.id.startsWith('-'));
    if (content.text.length > 2000) return;
    const key = JSON.stringify([message.platform, space.id, sender, message.id]);
    if (delivered.has(key)) return;
    for (const [id, timestamp] of delivered) if (now() - timestamp > 3600000) delivered.delete(id);
    const authorized = message.platform === 'terminal' || allowed[message.platform as keyof AllowedSenders].has(sender);
    let text = content.text.trim();
    if (message.platform === 'telegram') {
      const command = /^\/(\w+)(?:@([A-Za-z0-9_]+))?(?:\s+([\s\S]*))?$/.exec(text);
      if (command?.[2] && command[2].toLowerCase() !== botUsername?.toLowerCase()) return;
      if (!isGroup && (command?.[1] === 'whoami' || (!authorized && command?.[1] === 'start'))) {
        try {
          await space.send(`Your Telegram user ID is ${sender}. Add it to SPECTRUM_TELEGRAM_ALLOWED_SENDERS in BRH_Test/.env and restart the dashboard and worker to enable Rover. Your bot is connected through Photon Spectrum.`);
          delivered.set(key, now());
        } catch { console.error('Could not deliver Telegram setup instructions.'); }
        return;
      }
      if (command?.[1] === 'start' || command?.[1] === 'help') text = isGroup ? 'Rover, help' : 'help';
      if (command?.[1] === 'rover') text = 'Rover, ' + (command[3] || 'help');
    }
    if (!authorized) return;
    if (isGroup && !/^\s*@?(sortrover|rover)[,:\s]+/i.test(text)) return;
    try {
      await space.responding(async () => {
        const result = await request({ platform: message.platform, space_id: space.id, sender_id: sender,
                                       message_id: message.id, text, is_group: isGroup });
        if (result.reply) await space.send(result.reply);
      });
      delivered.set(key, now());
    } catch (error) {
      if (error instanceof BridgeError && error.status === 403) return;
      console.error('Could not process a Spectrum message; check the backend and connection.');
      try { await space.send('The dashboard is temporarily unavailable. Retry your last message; confirmed drops are protected against duplicate points.'); }
      catch { console.error('Could not deliver the connection fallback.'); }
    }
  };
}
