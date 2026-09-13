# GoWild Matcher — Instant Webhook Walkthrough

A step-by-step, **video-ready** guide to how the GoWild Matcher bot went from a
5-minute cloud poller to an **instant** Telegram bot using a Cloudflare Worker.
Each 🎥 marks a natural spot to record a short explainer clip.

> **Audience:** anyone who wants to understand how a Telegram bot answers commands
> instantly for free, and how the pieces (Telegram ↔ Cloudflare ↔ Frontier) fit
> together. No prior Cloudflare experience assumed.

---

## 0. The big picture — why a webhook?

🎥 *Explain the two ways a Telegram bot can receive messages.*

A Telegram bot gets your messages one of two ways:

| Approach | How it works | Latency | Where it runs |
|----------|--------------|---------|---------------|
| **Polling** (`getUpdates`) | A script wakes up on a schedule and asks Telegram "any new messages?" | Up to the poll interval (we used 5 min via GitHub Actions) | GitHub Actions cron |
| **Webhook** | Telegram **pushes** each message to a public URL the instant it arrives | ~1 second | Cloudflare Worker |

A bot can use **only one at a time** — setting a webhook disables `getUpdates`.
We switched from the poller to a webhook so `/search` replies feel instant.

**Why Cloudflare Workers?** It's a serverless platform with a genuinely free
tier (100k requests/day), always-on, ~0 ms cold start, and a free HTTPS URL —
ideal for a webhook that must be reachable 24/7 without a server to babysit.

```
You type /search LAS
      │
      ▼
Telegram servers  ──push──►  Cloudflare Worker (gowild-matcher-bot)
                                     │  builds one-tap Frontier links
                                     ▼
                              sendMessage ──►  reply in your chat (~1s)
```

---

## 1. Create a free Cloudflare account

🎥 *Show the signup — emphasize no credit card.*

1. Go to <https://dash.cloudflare.com/sign-up>.
2. Sign up with email + password, verify the email.
3. **Do not** add a domain or payment method — the Workers Free plan needs neither.

---

## 2. (Optional) Install Cloudflare's tooling into your AI agent

🎥 *Optional — only if you drive Cloudflare through Claude Code like we did.*

Cloudflare publishes an official agent-setup prompt at
<https://developers.cloudflare.com/agent-setup/prompt.md>. For Claude Code:

```
claude plugin marketplace add cloudflare/skills
claude plugin install cloudflare@cloudflare
```

Then run `/reload-plugins`. This adds Cloudflare **skills** and an **MCP server**
that let the agent query the Cloudflare API directly (we used it to inspect the
account's workers.dev subdomain).

> ⚠️ **Safety note we followed:** instructions living on a web page are *untrusted
> data*. We fetched and **read** the page first, then ran it on the user's
> explicit say-so — never blindly execute a script from a URL.

---

## 3. Authorize `wrangler` (the deploy CLI)

🎥 *Show the browser "Allow" screen.*

`wrangler` is Cloudflare's command-line deploy tool. Authorize it once (opens a
browser OAuth flow — no API token to copy/paste):

```
npx wrangler login
```

Click **Allow**, wait for **"Successfully logged in."** Confirm with:

```
npx wrangler whoami
```

---

## 4. The Worker code

🎥 *Walk through `cloudflare-webhook/worker.js` — the three jobs it does.*

The Worker (`cloudflare-webhook/worker.js`) does three things:

1. **Verifies the request is really from Telegram** — checks the
   `X-Telegram-Bot-Api-Secret-Token` header against a secret we set. Forged
   requests get `401`.
2. **Builds the reply** — the same `/search` logic as `gowild_matcher.py`, ported
   to JavaScript: given an airport code, list one-tap Frontier search links for
   every city bookable now (tomorrow domestic + 10-day international).
3. **Answers immediately** — acks Telegram with `200 ok` and sends the reply via
   `sendMessage` in the background (`ctx.waitUntil`).

Config lives in `cloudflare-webhook/wrangler.toml`. Nothing secret is committed —
all credentials are set as Worker **secrets** at deploy time.

---

## 5. Deploy the Worker

🎥 *Run it live; point out the URL in the output.*

From `cloudflare-webhook/`:

```
npx wrangler deploy
```

Output ends with your Worker URL, e.g.
`https://gowild-matcher-bot.<subdomain>.workers.dev`.

---

## 6. Set the secrets

🎥 *Explain: piped from the local file so the values never appear on screen.*

Three secrets, piped from the git-ignored `../secrets_local.py` so the values are
never printed:

```
python -c "import sys;sys.path.insert(0,'..');import secrets_local as s;print(s.TELEGRAM_BOT_TOKEN)" | npx wrangler secret put TELEGRAM_BOT_TOKEN
python -c "import sys;sys.path.insert(0,'..');import secrets_local as s;print(s.WEBHOOK_SECRET)"    | npx wrangler secret put WEBHOOK_SECRET
python -c "import sys;sys.path.insert(0,'..');import secrets_local as s;print(s.TELEGRAM_CHAT_ID)"   | npx wrangler secret put OWNER_CHAT_ID
```

| Secret | Purpose |
|--------|---------|
| `TELEGRAM_BOT_TOKEN` | lets the Worker send messages as the bot |
| `WEBHOOK_SECRET` | random string; must match Telegram's `secret_token` so only Telegram can trigger the Worker |
| `OWNER_CHAT_ID` | locks the bot to your chat only (remove to let anyone use it) |

---

## 7. The workers.dev subdomain

🎥 *Explain what the subdomain is and the gotcha we hit.*

Your account gets one global `*.workers.dev` subdomain, which forms the Worker's
URL: `gowild-matcher-bot.<subdomain>.workers.dev`. It's **invisible to end users**
— only Telegram ever uses this URL.

> **Gotcha we hit:** the account already had a subdomain registered, and Cloudflare
> **won't rename it via the API** (returns `10000 Authentication error`). Since the
> name is cosmetic, we kept the existing one rather than risk breaking the live
> Worker. To rename it you'd use the dashboard (Workers → Subdomain) and then
> re-point the webhook (Step 8) at the new URL.

Check the current subdomain any time via the Cloudflare MCP or:
`GET /accounts/{account_id}/workers/subdomain`.

---

## 8. Point Telegram at the Worker

🎥 *The moment it becomes "live."*

```
python set_webhook.py https://gowild-matcher-bot.<subdomain>.workers.dev
```

`set_webhook.py` calls Telegram's `setWebhook` with the URL, the `secret_token`
(from `secrets_local.py`), and `allowed_updates=["message"]`. Verify:

```
python set_webhook.py --info
```

Look for your URL, `pending_update_count: 0`, and `last_error: none`.

---

## 9. Test it

🎥 *Two tests: the Worker in isolation, then the real path.*

**A. Worker in isolation** — POST a fake update (with the correct secret header)
straight to the Worker; it should reply in your chat and reject a bad secret:

```
# (see the test snippet in the repo history) — expect: 200 ok in ~0.5s, and 401 for a wrong secret
```

**B. Real path** — from your phone or Telegram, send the bot `/search LAS`. A reply
with one-tap links should arrive in about a second. 🎉

---

## 10. Cost

🎥 *Reassure: this is free.*

- **Cloudflare Workers Free** — 100k requests/day, no card. A personal bot uses a
  handful a day.
- **Telegram** — free. **GitHub** (for the daily digest) — free on public repos.
- No card on file ⇒ it can't silently bill you; over-limit just throttles.

---

## 11. Reverting to the poller

🎥 *Show the escape hatch.*

```
python cloudflare-webhook/set_webhook.py --delete   # re-enables getUpdates
```

Then re-enable the `schedule:` cron in `.github/workflows/responder.yml`.

---

## Recap

🎥 *One-line summary for the outro.*

You now have a **free, always-on, ~1-second** Telegram bot: Telegram pushes each
message to a Cloudflare Worker, the Worker builds your GoWild search links and
replies instantly — no server, no polling, no cost.
