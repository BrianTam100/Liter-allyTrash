# Use SortRover through Telegram and Photon Spectrum

The Telegram provider is implemented. It uses the same Rover companion, persistent
conversation memory, recycling records, confirmations, and rewards as the dashboard.
It needs your Telegram account and bot token before a live connection can be tested.

## Create your account and bot

1. Install the official [Telegram mobile app](https://telegram.org/apps) on your
   phone. Create your account with your mobile number and finish the verification
   shown in the app. This is your personal account; the bot is created separately.
2. Open the official [@BotFather](https://t.me/BotFather) inside Telegram. Send
   `/newbot`, choose a display name such as **SortRover**, and choose an available
   username ending in `bot`, such as `YourTeamSortRoverBot`.
3. BotFather returns an API token. Save it directly in `BRH_Test/.env`:

   ```dotenv
   SPECTRUM_PROVIDER=telegram
   SPECTRUM_TELEGRAM_BOT_TOKEN=PASTE_THE_BOTFATHER_TOKEN_HERE
   SPECTRUM_TELEGRAM_ALLOWED_SENDERS=
   ```

   Keep the existing Photon project ID, project secret, bridge key, database, and
   xAI settings. Do not paste the bot token into chat or commit it. No iMessage
   number is needed for the Telegram provider. You do not need a Telegram `api_id`
   or `api_hash`; this integration uses the Bot API.

## Start and authorize yourself

After saving the token, tell Codex **“Telegram token saved”** to finish startup.
For manual startup, restart the Python dashboard to load the new environment,
then from the `spectrum` folder run:

```powershell
npm run build
node dist/doctor.js --cloud
npm start
```

Stop an existing background worker first with `./spectrum/Stop.ps1` from the
repository root. Use `./spectrum/Start.ps1` instead of `npm start` if you want the
worker to run in the background. Keep the Python dashboard and one Spectrum worker
running. Provider changes take effect on restart.

Spectrum automatically registers the Telegram webhook with Photon's Fusor service
when the worker starts. The laptop connects to Photon; you do not need to expose
the local dashboard with a public tunnel.

1. Open your new bot using the link BotFather gave you, and tap **Start**.
2. The bot replies with your numeric Telegram user ID. You can also send `/whoami`
   in a private chat with the bot.
3. Put that ID in `BRH_Test/.env`, for example:

   ```dotenv
   SPECTRUM_TELEGRAM_ALLOWED_SENDERS=123456789
   ```

4. Restart the Python dashboard and Spectrum worker again. Now send `progress`
   or `log 2 plastic bottles in recycling`, followed by the returned confirmation
   code after depositing the items.

The allowlist takes numeric **user IDs**, not phone numbers, bot IDs, chat IDs, or
usernames. Separate teammate IDs with commas. Until authorized, users can only
receive their own ID through private `/start` or `/whoami`; they cannot access
shared Pilot records. The iMessage allowlist is separate.

## Group chats

Add the bot to the group. With Telegram's default bot privacy mode, use
`/rover@YourBotUsername progress` or `/rover@YourBotUsername confirm ABC123`.
Messages addressed to another bot are ignored. When Telegram delivers ordinary
group text, `Rover, progress` also works. Ordinary group conversation is ignored.
The implementation handles both basic groups and supergroups.

## Connection checks

The dashboard shows **Telegram agent running** when the worker is active.
`node dist/doctor.js --cloud` checks the bot token with Telegram and verifies
Photon project/Fusor authentication. Phone-to-bot delivery is verified only when
you receive a reply to an actual Telegram message.

Incoming webhook verification uses a stable secret derived from the local bridge
key. Advanced deployments can set `SPECTRUM_TELEGRAM_WEBHOOK_SECRET` explicitly.
If you rotate that secret or the bridge key after initial registration, clear the
old Telegram webhook before restarting: Spectrum's SDK does not replace the secret
when the webhook URL has stayed the same. Never run another polling/webhook service
for this bot at the same time.

Sources: [Telegram account FAQ](https://telegram.org/faq),
[BotFather tutorial](https://core.telegram.org/bots/tutorial),
[Spectrum Telegram setup](https://photon.codes/docs/spectrum-ts/providers/telegram/setup).
