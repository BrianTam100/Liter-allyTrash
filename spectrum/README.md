# SortRover + Spectrum

**Using Telegram instead of iMessage?** Follow [the Telegram setup guide](TELEGRAM.md),
starting with account creation and BotFather. Set `SPECTRUM_PROVIDER=telegram`;
the worker supports either Telegram or iMessage with separate sender allowlists.
Telegram shares the companion and database described below. The iMessage-specific
line setup in this guide is only needed when `SPECTRUM_PROVIDER=imessage`.

This uses Photon's stable TypeScript SDK and managed iMessage provider. The
Node worker receives messages over Spectrum's persistent connection, calls the
existing Python dashboard through a private authenticated bridge, and responds
in the originating conversation. No public webhook URL or tunnel is required.

SDK packages are pinned to 12.10.1. The OpenTelemetry core dependency is overridden
to its compatible patched 2.8.0 release; the installed dependency audit is clean.

The same Rover companion is available on the dashboard. It reads the existing
Pilot's progress, recent drops, and rover status, gives sorting advice using the
xAI, with local guidance as a fallback, and proposes drops for explicit human confirmation.
The model has no write or hardware tools. Conversation transcripts and pending
actions survive restarts in the configured TigerData PostgreSQL or SQLite database.
Confirmed collections are shared across interfaces; conversational memory is
scoped to the sender and conversation. This project uses a shared Pilot rather
than separate depositor accounts.

## Account connection

1. Open [Photon dashboard](https://app.photon.codes/dashboard). In project Settings,
   copy your project ID and project secret into `BRH_Test/.env`:

   ```dotenv
   SPECTRUM_PROJECT_ID=your-project-id
   SPECTRUM_PROJECT_SECRET=your-project-secret
   SPECTRUM_BRIDGE_KEY=a-long-random-local-secret
   SPECTRUM_ALLOWED_SENDERS=+15551234567,+15557654321
   SPECTRUM_BACKEND_URL=http://127.0.0.1:8000
   XAI_CHAT_MODEL=grok-4.7
   ```

   Keep the existing `DATABASE_URL`, `SECRET_KEY`, and `XAI_API_KEY`. Never paste
   keys into browser code or commit `.env`. Generate the bridge key using
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` if not already set.
   The Python dashboard and worker must load the same key. Remote backend URLs
   require HTTPS with a trusted certificate; local loopback HTTP works.

2. Apply `HACKWITHPHOTON` in Photon if still available for your account, and enable
   or assign an iMessage line to this project. Provisioning and promo eligibility
   are managed in the dashboard. Dedicated lines are needed for group features
   that Photon restricts to dedicated lines. Text the assigned agent number from
   a phone or Apple ID listed in `SPECTRUM_ALLOWED_SENDERS`.

3. Start or restart the Python dashboard **after** saving the environment:

   ```powershell
   .\BRH_Test\.venv\Scripts\python.exe web_server.py --host 127.0.0.1 --http --no-lid --no-model-load
   ```

4. In a second terminal:

   ```powershell
   cd spectrum
   npm ci
   npm run build
   npm run doctor
   node dist/doctor.js --cloud
   npm start
   ```

   The SDK discovers assigned project lines and renews their tokens. Keep both
   processes running on the laptop. Stop the worker with Ctrl+C. Run one dashboard
   process per physical rover. When credentials or allowed senders change, restart
   both processes. Connection status on the dashboard expires if the worker stops.

   On Windows, `./spectrum/Start.ps1` starts the built worker in the background;
   `./spectrum/Stop.ps1` stops that worker. Its logs and PID are kept in the ignored
   `BRH_Test/.instance` directory. These scripts leave the Python server running.

## Try it

Text `help`, `progress`, `recent`, `rover status`, or `Where does cardboard go?`.
Send `log 2 plastic bottles in recycling`, deposit the items, then send the
returned `confirm ABC123` code within five minutes. `cancel` discards the proposal.
Only its initiating sender in the same conversation can confirm it; a new proposal
replaces the previous pending one. Confirmations and duplicate incoming message
IDs cannot award points twice. Manual confirmation is not sensor verification.

In group conversations, start messages with `Rover,` or `SortRover,`. Other group
messages, non-text content, outbound echoes, unauthorized senders, and messages
older than five minutes are ignored. Photo scanning and voice/gesture driving
remain available through the existing dashboard; this integration handles text
and threaded text replies. Movement stays with the existing local controls.

Each conversation can send up to 20 new messages per minute, with a shared limit
of 100 per minute per Python process. Retries of completed events remain available.

`forget` clears this sender's conversational memory and pending proposal in the
current chat while preserving confirmed collections. Transcripts retain 12 turns;
replay receipts expire after 30 days. Messages sent to the conversation model use
`store: false`. Sorting advice falls back to local guidance when xAI is unavailable.

For a credential-free Spectrum transport demo, with the dashboard running:

```powershell
node dist/doctor.js --terminal
npm run terminal
```

## Checks

```powershell
# Repository root
.\BRH_Test\.venv\Scripts\python.exe -m unittest BRH_Test.test_companion
# spectrum directory
npm run build
npm test
```

Tests use isolated databases and simulated incoming events. Live iMessage delivery
requires the actual Photon project, assigned line, and an inbound test message.
`doctor` verifies local configuration and bridge authentication. `node dist/doctor.js --cloud`
also checks Photon project authentication, iMessage token issuance, and assigned lines;
it does not claim delivery to an Apple device.

SDK references: [quickstart](https://photon.codes/docs/spectrum-ts/getting-started),
[managed iMessage](https://photon.codes/docs/spectrum-ts/providers/imessage),
[message shapes](https://photon.codes/docs/spectrum-ts/messages).

See [Gemini setup and reliability](../BRH_Test/GEMINI.md) for the separate photo and disposal guide on the dashboard.
