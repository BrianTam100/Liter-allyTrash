# Gemini Sort Guide

Gemini has a separate guide at `/gemini`, linked at the bottom of the sidebar
above Settings. Upload a photo or
describe an item to get material guidance, preparation steps, reuse ideas, and
questions to verify locally. Rover chat and Spectrum iMessage use xAI separately.

```dotenv
GEMINI_API_KEY=your-key
GEMINI_CHAT_MODEL=gemini-3.7-flash
GEMINI_FALLBACK_MODELS=gemini-3.7-flash,gemini-3.8-flash,gemini-3.1-flash-lite
```

Keys remain in `BRH_Test/.env` on the server. Restart the Python dashboard after
changing configuration. No additional key is needed in the browser or Spectrum.

The guide uses Google's [stable Interactions API](https://ai.google.dev/api/interactions-api-v1)
for 3.7 Flash and 3.1 Flash-Lite, and the [v1beta Interactions API](https://ai.google.dev/api/interactions-api)
for 3.8 Flash, which is listed in that reference.
It sends only the submitted question, optional location, and selected photo;
it does not send Pilot records or Rover conversation history. Each analysis is
independent. `store: false` disables interaction storage; Google still processes
the submitted content under the account's API terms. The app does not persist
photos or analysis results. Reloading the page clears the displayed analysis.

JPEG, PNG, and WebP uploads are validated by decoding the actual image, limited
to 5 MB and 25 million pixels, resized to 1280 pixels, and re-encoded without EXIF.
The guide is advisory: it has no tools to record drops, award points, or drive.
It does not look up live municipal rules or collection facilities.

## Reliability

The configured primary model is tried first, followed by every model in
`GEMINI_FALLBACK_MODELS`, skipping duplicates. The defaults are 3.7 Flash,
3.8 Flash, and 3.1 Flash-Lite. Each model is attempted once, with an eight-second
socket timeout. Any HTTP error (including 400, 429, and 503), network error,
or empty, malformed, or incomplete response advances to the next model.
The first successful answer ends the chain. The same text and photo are sent
to each attempted model. An empty fallback list disables additional models.

Cooldowns apply only after all models fail. Authentication/configuration failures
pause requests for five minutes; quota failures pause them for one minute.
Three failed requests open a one-minute
circuit. Four simultaneous analyses are allowed per process; existing per-session
and global request limits also apply. Socket timeouts are not a strict wall-clock
deadline. The browser stops waiting after 40 seconds and preserves inputs.

The guide explicitly reports unavailable, malformed, or incomplete responses.
It does not substitute another provider's answer for Gemini. It displays only
final text as plain text, never model HTML or thoughts. CSRF protection applies
to the analysis endpoint. Browser output is transient and separate from chat.

## Verification

From the repository root:

```powershell
.\BRH_Test\.venv\Scripts\python.exe -m BRH_Test.ai_doctor
.\BRH_Test\.venv\Scripts\python.exe -m unittest BRH_Test.test_gemini_guide BRH_Test.test_ai_client BRH_Test.test_companion
```

The doctor makes a small live Gemini text request and exits nonzero on failure.
Tests use fake providers and isolated databases. They cover uploads, metadata
removal, CSRF, rate limits, provider separation, failure recovery, and prevention
of ledger writes. Gemini 3.7 Flash was verified with this account; availability
can still vary. The doctor prints the successful model and all models attempted.
