# GoWild Matcher 🎟️

A [searchgwp.com](https://searchgwp.com)-style Telegram bot for the **Frontier
Airlines GoWild! Pass**. Every morning it works out which flights are inside the
GoWild booking window right now and, for each of your origin airports, sends a
**one-tap link straight into the exact Frontier search** — so you open your
logged-in Frontier app and see the live GoWild seats, then book.

Runs in **GitHub Actions**, so it fires whether or not your computer is on, and
delivers to **Telegram on your phone** — the same architecture as its siblings
(`fare-watcher`, `gowild-scout`, `nyc-free-events`, `tech-networking-scout`).

---

## How it works

Frontier has **no public availability API**, and the GoWild *price / seat count*
only appears once you're **logged into a GoWild account** inside Frontier's own
site or app. Scraping that unattended (what the paid searchgwp / gopassflights
services do) constantly fights Frontier's bot protection and account/login walls.

So this bot splits the job the honest, reliable way:

| Job | Where |
|-----|-------|
| Time the GoWild booking windows, fan out every city, build the exact search links | **Cloud (this bot)** — 24/7, ToS-safe |
| Show the real live GoWild fare + seat count, and book | **Your Frontier app** — one tap away |

### GoWild booking windows

- **Domestic** — confirmable the **day before** departure (and often same day).
  → the bot surfaces flights departing **today + tomorrow**.
- **International** — bookable up to **10 days** before departure.
  → the bot surfaces flights departing **~10 days out** (passport required).

Each run shows a rotating slice of the destination catalog per origin (seeded by
the date) so you cover the **whole network** over successive days without a giant
message. Blackout dates (Peak Day Charge) are flagged with ⚠️. De-dupes on
`(origin, dest, date)` via `seen.json` so a re-run the same day won't repeat.

---

## Files

| File | Purpose |
|------|---------|
| `gowild_matcher.py` | Main agent — windows, deep links, rotation, Telegram, Claude blurb |
| `airports.py` | Frontier hubs + destination catalog, blackout dates, helpers |
| `secrets_local.py` | Bot token + chat id (git-ignored; env vars win in the cloud) |
| `requirements.txt` | `requests`, `anthropic` |
| `.github/workflows/daily.yml` | Cloud schedule (13:00 UTC daily) |
| `register_task.ps1` | Optional local Windows Task Scheduler job (daily 8 AM) |

## Commands

```bash
python gowild_matcher.py --preview        # console dry run, no Telegram, no state change
python gowild_matcher.py --origin LAS     # searchgwp-style: every city from ONE airport, printed
python gowild_matcher.py --chatid         # discover your Telegram chat id
python gowild_matcher.py                   # real run — send matches to Telegram
```

## Configuration (`gowild_matcher.py`)

- **`MY_ORIGINS`** — airports to watch. Defaults to your home hubs
  `PHL / EWR / LGA / JFK`. To watch **every Frontier US hub**, set
  `MY_ORIGINS = list(APT.US_HUBS)`, or set the `MY_ORIGINS` env var / repo
  variable to a comma list (e.g. `PHL,EWR,LAS,DEN`).
- **`DOMESTIC_PER_ORIGIN` / `INTL_PER_ORIGIN`** — how many cities per origin per
  run (the rest rotate in on later days).
- **`HAVE_PASSPORT`** — set `False` to hide international destinations.
- **`INCLUDE_SAME_DAY`** — also show same-day (today) domestic day-trip links.

## Deploy

**Cloud (recommended, runs when your PC is off):**
1. Push to a GitHub repo.
2. Add repo **Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
   (optional) `ANTHROPIC_API_KEY`.
3. Optional repo **Variable** `MY_ORIGINS` to override the origins.
4. The workflow runs daily at 13:00 UTC; trigger it manually from the Actions
   tab (`workflow_dispatch`) to test.

**Local (optional):** `.\register_task.ps1` registers a silent daily 8 AM task.

---

## Caveats & honesty notes

- **It does not show seat counts** — it hands you the exact search; Frontier
  shows the live GoWild availability when you tap (you must be logged into your
  GoWild account). This is deliberate: a reliable, ToS-safe cloud bot cannot see
  the logged-in GoWild fare.
- **The destination catalog is a broad, well-known subset** of Frontier's ~90
  US airports plus its Caribbean / Mexico / Latin America network. A deep link
  to a route Frontier doesn't fly just shows "no flights" — harmless. Verify or
  extend `airports.py` against the live
  [route map](https://www.flyfrontier.com/travel/route-map/).
- **Blackout dates** were sourced for the 2026 Fall/Winter pass — re-verify on
  the [GoWild page](https://www.flyfrontier.com/deals/gowild-pass/); Frontier
  updates them.
