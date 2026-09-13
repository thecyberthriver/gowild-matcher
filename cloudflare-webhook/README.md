# GoWild Matcher — instant webhook (Cloudflare Worker)

Answers `/search` and `/help` **the instant you send them** — no 5-min poll.
Telegram POSTs each update straight to this Worker, which replies immediately.

This replaces the `responder.yml` poller (a Telegram bot can't use a webhook and
`getUpdates` polling at the same time — the poller is left disabled while the
webhook is active).

## What it does
Same `/search` logic as `gowild_matcher.py` (web-mode https links): given an
airport code, it returns one-tap Frontier search links for every city bookable
now — tomorrow (domestic) + 10 days out (international). Tap → Frontier shows the
live GoWild seats when you're logged into your GoWild account.

## One-time setup

**1. Cloudflare account** (free, no card): sign up at https://dash.cloudflare.com/sign-up

**2. Log wrangler in** (opens a browser to authorize — no token pasting):
```
npx wrangler login
```

**3. Deploy + wire up** (run from this folder; secrets are piped from the
untracked `../secrets_local.py`, never printed):
```
npx wrangler deploy
python - <<'PY' | npx wrangler secret put TELEGRAM_BOT_TOKEN
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.TELEGRAM_BOT_TOKEN)
PY
python - <<'PY' | npx wrangler secret put WEBHOOK_SECRET
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.WEBHOOK_SECRET)
PY
python - <<'PY' | npx wrangler secret put OWNER_CHAT_ID
import sys; sys.path.insert(0,".."); import secrets_local as s; print(s.TELEGRAM_CHAT_ID)
PY
```

**4. Point Telegram at the Worker** (uses the deployed `*.workers.dev` URL):
```
python set_webhook.py https://gowild-matcher-bot.<your-subdomain>.workers.dev
```

## Bindings
| Name | Kind | Purpose |
|------|------|---------|
| `TELEGRAM_BOT_TOKEN` | secret | bot token |
| `WEBHOOK_SECRET` | secret | matches Telegram's `setWebhook` secret_token (rejects forged posts) |
| `OWNER_CHAT_ID` | secret | only this chat is answered (remove to answer anyone) |

## Reverting to the poller
```
python set_webhook.py --delete     # deleteWebhook re-enables getUpdates
```
Then re-enable the `schedule:` cron in `.github/workflows/responder.yml`.
