# Credentials & Live-Call Setup (≈15 min)

Goal: fill `.env` with real values so the live-call preflight turns green and we can place call #1.

The code reads exactly these variables (see `app/config.py`):

| `.env` variable | What it is | Where it comes from |
| --------------- | ---------- | ------------------- |
| `TELEPHONY_ACCOUNT_ID` | Twilio **Account SID** | Twilio Console home |
| `TELEPHONY_AUTH_TOKEN` | Twilio **Auth Token** | Twilio Console home |
| `TELEPHONY_FROM_NUMBER` | Your Twilio voice number (E.164) | Twilio phone numbers |
| `LLM_API_KEY` | OpenAI API key | OpenAI dashboard |
| `STT_API_KEY` | **Same** OpenAI key | OpenAI dashboard |
| `TTS_API_KEY` | **Same** OpenAI key | OpenAI dashboard |
| `PUBLIC_BASE_URL` | Public HTTPS URL of your local server | ngrok |
| `ENABLE_REAL_CALLS` | Set to `true` only when ready to dial | you |

One OpenAI key fills all three `*_API_KEY` slots (it's used for the LLM, STT, and TTS calls).

---

## Step 1 — OpenAI key (≈3 min)

1. Go to <https://platform.openai.com/signup> and sign in / create an account.
2. Add a payment method: **Billing → Payment methods**. Load ~$10 of prepaid credit (plenty; the whole challenge runs under $20).
3. Go to **<https://platform.openai.com/api-keys>** → **Create new secret key** → copy it (starts with `sk-...`). You only see it once.
4. Paste that one key into `LLM_API_KEY`, `STT_API_KEY`, and `TTS_API_KEY`.

> Models used (already set in code, no action needed): `gpt-4o-mini` (LLM), `gpt-4o-transcribe` (STT), `gpt-4o-mini-tts` (TTS).

## Step 2 — Twilio account + number (≈7 min)

1. Sign up at **<https://www.twilio.com/try-twilio>** (free trial includes credit). Verify your email and your personal phone.
2. On the **Twilio Console** home page, copy:
   - **Account SID** → `TELEPHONY_ACCOUNT_ID`
   - **Auth Token** (click to reveal) → `TELEPHONY_AUTH_TOKEN`
3. Buy a voice number: **Phone Numbers → Manage → Buy a number** → filter **Capabilities: Voice** → buy a US local number (~$1/mo). Copy it in E.164 form, e.g. `+15551234567` → `TELEPHONY_FROM_NUMBER`.
   - Trial note: trial accounts can only call **verified** numbers. The assessment line `+1-805-439-8008` is a normal callable number, but if Twilio blocks the outbound call on trial, upgrade the account (add ~$20) to remove the restriction. We'll see this in the preflight/first call and decide then.

## Step 3 — Public tunnel (≈2 min, we do this together at call time)

Twilio needs to reach your laptop over HTTPS for the media stream.

1. Install ngrok: `brew install ngrok` (or download from ngrok.com), then `ngrok config add-authtoken <token>` after a free signup.
2. At call time you'll run `make serve` in one terminal and `ngrok http 8000` in another.
3. Copy the `https://….ngrok-free.app` URL ngrok prints → `PUBLIC_BASE_URL`. Leave `ENABLE_REAL_CALLS=false` until we're ready.

---

## Step 4 — Fill `.env`

```bash
cp .env.example .env
# then edit .env with the values above
```

Keep these as-is (already correct): `AUTHORIZED_DESTINATION=+18054398008`, `MAX_CALL_DURATION_SECONDS=180`, `MAX_CALLS_PER_RUN=1`, `MONTHLY_COST_LIMIT_USD=20`.

## Step 5 — Tell me you're done

Don't paste the secret values here. Just say the keys are in `.env` and ngrok is running. Then we run:

```bash
python scripts/preflight_live_call.py --scenario scenarios/01_simple_scheduling.yaml
```

When that's green, we place call #1, listen, fix whatever breaks (this becomes your AI-debugging Loom), and loop through the 12 scenarios to clear the 10-call minimum.

> `.env` is gitignored — never commit it. Only the placeholder `.env.example` stays in the repo.
