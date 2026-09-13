#!/usr/bin/env python3
"""
gowild_matcher.py — Frontier GoWild Pass flight matcher (Telegram agent).

A searchgwp.com-style helper for your Frontier GoWild Pass. Each run it looks at
which flights are INSIDE the GoWild booking window right now and, for each of
your origin airports, sends a one-tap link straight into the exact Frontier
search — so you open your logged-in Frontier app and see the live GoWild seats.

Why deep links instead of scraping seat counts
----------------------------------------------
Frontier has no public availability API, and the GoWild *fare/seat count* only
appears once you're logged into a GoWild account inside Frontier's own site/app.
Scraping that unattended (what searchgwp/gopassflights sell) fights Frontier's
bot protection and breaks constantly. So this bot does the reliable, ToS-safe
part in the cloud — it times the GoWild booking windows and hands you a
pre-filled search for every city — and lets your phone's Frontier app show the
real GoWild availability the instant you tap.

GoWild booking windows (airports.py):
  • Domestic  — confirmable the DAY BEFORE departure (and often same day).
  • International — bookable up to 10 DAYS before departure.
So each run surfaces domestic flights departing today/tomorrow and international
flights departing ~10 days out — the flights you can actually grab right now.

Runs in the cloud (GitHub Actions) so it fires whether or not your PC is on, and
delivers to Telegram on your phone. De-dupes on (origin, dest, date) via
seen.json so a second run the same day won't repeat itself.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import airports as APT

# Windows consoles default to cp1252 and choke on the emoji this agent prints.
# Force UTF-8 on stdout/stderr so --preview and logging never crash. (Telegram
# always gets clean UTF-8 via JSON regardless of this.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------------------
# CONFIG — edit these
# ---------------------------------------------------------------------------

# Dedicated Telegram bot for GoWild matches. Message @BotFather -> /newbot, make
# e.g. @gowild_matcher_bot, and put its token + your chat id in secrets_local.py.
# Env vars (GitHub Actions Secrets) win; secrets_local.py fills gaps locally.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "CHANGE-ME:paste-token-from-BotFather")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "CHANGE-ME-chat-id")

# Which origin airports to watch. Defaults to your home hubs (where you actually
# start a trip). To watch EVERY Frontier US hub instead, use:
#     MY_ORIGINS = list(APT.US_HUBS)
# Or set the MY_ORIGINS env var to a comma list, e.g. "PHL,EWR,LAS,DEN".
MY_ORIGINS = APT.HOME_HUBS

_env_origins = os.environ.get("MY_ORIGINS", "").strip()
if _env_origins:
    MY_ORIGINS = [a.strip().upper() for a in _env_origins.split(",") if a.strip()]

# How many destinations to show per origin, per run. The full catalog rotates in
# over successive days (seeded by the date) so you cover every city without a
# giant daily message.
DOMESTIC_PER_ORIGIN = 7
INTL_PER_ORIGIN = 3

# On-demand /search caps (popular cities first). Kept modest so a reply is a few
# messages, not a dozen — app-mode links are long. Unserved routes just show
# "no flights" when tapped, so these are the highest-value ones to surface.
SEARCH_DOMESTIC_CAP = 16
SEARCH_INTL_CAP = 8

# Passport: set False to hide international destinations entirely.
HAVE_PASSPORT = True

# Link mode for the tappable city links:
#   "web" — plain https link (DEFAULT, recommended). Tappable in Telegram; opens
#           Frontier pre-filled to the exact route + date. On Android it opens the
#           Frontier APP automatically IF the app has verified app-links for the
#           domain, otherwise the mobile site. Either way the route/date is kept.
#   "app" — Android intent:// link with a web fallback. NOT RECOMMENDED: Telegram
#           renders intent:// links as PLAIN, NON-TAPPABLE TEXT (verified), so the
#           city names stop being clickable. Left only as an experiment.
# IMPORTANT (Android): for GoWild PRICES to show, the tap must land where you're
# logged into GoWild. Telegram's in-app browser has its own cookies, so either set
# Telegram → Settings → "open links in external browser", or long-press a link and
# choose Chrome / the Frontier app. (env var LINK_MODE overrides this default.)
LINK_MODE = os.environ.get("LINK_MODE", "web").strip().lower() or "web"
FRONTIER_ANDROID_PACKAGE = "com.flyfrontier.android"

# Also include a same-day (today) domestic set for last-minute day trips, on top
# of tomorrow's freshly-opened window.
INCLUDE_SAME_DAY = True

# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"
LOG_FILE = BASE_DIR / "gowild_matcher.log"

# --- Claude "best bet" blurb (optional) -------------------------------------
# Uses the Anthropic API (Claude Haiku) when ANTHROPIC_API_KEY is set — a GitHub
# repo Secret in the cloud. Degrades gracefully (no blurb) if the key is absent.
USE_LLM = True
CLAUDE_MODEL = "claude-haiku-4-5"
CLAUDE_TIMEOUT = 30
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_SYSTEM = "You are a savvy budget-travel scout. Reply with ONE punchy sentence, no preamble, no emoji."

# Local fallback (untracked) — only fills what the environment didn't provide,
# so GitHub Actions Secrets always win over secrets_local.py.
try:
    import secrets_local as _secrets
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        TELEGRAM_BOT_TOKEN = getattr(_secrets, "TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    if "CHANGE-ME" in TELEGRAM_CHAT_ID:
        TELEGRAM_CHAT_ID = getattr(_secrets, "TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)
    if not ANTHROPIC_API_KEY:
        ANTHROPIC_API_KEY = getattr(_secrets, "ANTHROPIC_API_KEY", "")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"sent": []}


def save_seen(seen: dict) -> None:
    seen["sent"] = seen.get("sent", [])[-4000:]  # cap growth
    try:
        SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"WARN could not write seen cache: {e}")


def _fmt(d: date) -> str:
    # Windows-safe day formatting (no %-d).
    return f"{d.strftime('%a %b')} {d.day}"


def web_link(origin: str, dest: str, dt: date) -> str:
    """Plain https Frontier search — lands on the results page pre-filled with
    origin/dest/date. GoWild legs book one-way, so we link one-way."""
    return (
        "https://booking.flyfrontier.com/Flight/InternalSelect"
        f"?o1={origin}&d1={dest}&dd1={dt:%Y-%m-%d}&ADT=1&mon=true"
    )


def deep_link(origin: str, dest: str, dt: date) -> str:
    """Tappable link honoring LINK_MODE. In "app" mode, an Android intent link
    that opens the Frontier app (package FRONTIER_ANDROID_PACKAGE) and falls back
    to the pre-filled web page; in "web" mode, the plain https page."""
    web = web_link(origin, dest, dt)
    if LINK_MODE != "app":
        return web
    # Android intent: URL — strip the scheme, add package + web fallback.
    path = web.split("://", 1)[1]
    fallback = urllib.parse.quote(web, safe="")
    return (
        f"intent://{path}#Intent;scheme=https;"
        f"package={FRONTIER_ANDROID_PACKAGE};"
        f"S.browser_fallback_url={fallback};end"
    )


def rotate(items: list[str], k: int, salt: str) -> list[str]:
    """Deterministically surface a rotating slice of `items` — a different slice
    each day (seeded by the ordinal date + salt) so the whole catalog cycles
    through over successive runs. Returns all items if there are <= k."""
    if not items or len(items) <= k:
        return list(items)
    seed = f"{date.today().toordinal()}-{salt}"
    rng = random.Random(seed)
    idx = list(range(len(items)))
    rng.shuffle(idx)
    # Offset the window by the day so slices advance instead of re-drawing.
    start = date.today().toordinal() % len(items)
    picks = [idx[(start + i) % len(idx)] for i in range(k)]
    return [items[i] for i in sorted(set(picks), key=picks.index)]


def ordered_dests(intl: bool, origin: str) -> list[str]:
    """Destinations of the requested kind (domestic/intl), popular ones first,
    excluding the origin itself."""
    pool = [c for c in APT.all_destinations(exclude={origin})
            if APT.is_international(c) == intl]
    pop = [c for c in APT.POPULAR if c in pool]
    rest = [c for c in pool if c not in pop]
    return pop + rest


def blackout_tag(d: date) -> str:
    return " ⚠️<i>blackout</i>" if APT.is_blackout(d) else ""


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tg_api(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def send_message(text: str) -> bool:
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN or "CHANGE-ME" in TELEGRAM_CHAT_ID:
        log("ERROR TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID still placeholder — edit secrets_local.py.")
        return False
    try:
        resp = requests.post(
            _tg_api("sendMessage"),
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        log(f"WARN telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Claude blurb (optional, degrades gracefully)
# ---------------------------------------------------------------------------

def best_bet(sample: list[str]) -> str | None:
    if not USE_LLM or not ANTHROPIC_API_KEY or not sample:
        return None
    prompt = (
        "From this list of Frontier GoWild destinations bookable right now, name "
        "the single best pick for a spontaneous cheap getaway this week and why, "
        "in ONE short sentence: " + ", ".join(sample)
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=CLAUDE_TIMEOUT)
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=80, system=LLM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip() or None
    except Exception as e:  # noqa: BLE001
        log(f"WARN claude blurb failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Match building
# ---------------------------------------------------------------------------

def domestic_dates() -> list[date]:
    """Domestic GoWild is confirmable the day before departure (and same day).
    Prime target = tomorrow (window just opened); optionally today too."""
    today = date.today()
    dates = [today + timedelta(days=1)]  # tomorrow — freshly opened
    if INCLUDE_SAME_DAY:
        dates.insert(0, today)           # today — last-minute day trips
    return dates


def intl_date() -> date:
    """International GoWild opens 10 days before departure — target that date."""
    return date.today() + timedelta(days=APT.INTERNATIONAL_WINDOW_DAYS)


def build_origin_block(origin: str, seen_set: set[str], new_keys: list[str]) -> tuple[str, list[str]]:
    """Return (message_html, sample_city_names) for one origin, or ("", []) if
    nothing new to show."""
    o_label = f"{APT.city(origin)} ({origin})"
    lines = [f"🛫 <b>{esc(o_label)}</b>"]
    sample: list[str] = []
    added = False

    # --- Domestic (today + tomorrow) ---
    dom = ordered_dests(intl=False, origin=origin)
    dom_pick = rotate(dom, DOMESTIC_PER_ORIGIN, salt=f"{origin}-dom")
    for dt in domestic_dates():
        row = []
        for d in dom_pick:
            key = f"{origin}|{d}|{dt.isoformat()}"
            if key in seen_set:
                continue
            row.append((d, dt))
            new_keys.append(key)
        if row:
            when = "today" if dt == date.today() else "tomorrow"
            lines.append(f"\n📅 <b>Depart {when} — {esc(_fmt(dt))}</b>{blackout_tag(dt)}  <i>(book now)</i>")
            for d, dd in row:
                lines.append(f"  • <a href=\"{esc(deep_link(origin, d, dd))}\">{esc(APT.city(d))} ({d})</a>")
                sample.append(APT.city(d))
            added = True

    # --- International (10 days out) ---
    if HAVE_PASSPORT:
        idt = intl_date()
        intl = ordered_dests(intl=True, origin=origin)
        intl_pick = rotate(intl, INTL_PER_ORIGIN, salt=f"{origin}-intl")
        row = []
        for d in intl_pick:
            key = f"{origin}|{d}|{idt.isoformat()}"
            if key in seen_set:
                continue
            row.append(d)
            new_keys.append(key)
        if row:
            lines.append(f"\n🌎 <b>International — depart {esc(_fmt(idt))}</b>{blackout_tag(idt)}  <i>(10-day window open)</i>")
            for d in row:
                lines.append(f"  • <a href=\"{esc(deep_link(origin, d, idt))}\">{esc(APT.city(d))} ({d})</a>  <i>passport</i>")
                sample.append(APT.city(d))
            added = True

    return ("\n".join(lines), sample) if added else ("", [])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    seen = load_seen()
    seen_set = set(seen.get("sent", []))
    new_keys: list[str] = []

    blocks: list[str] = []
    all_sample: list[str] = []
    for origin in MY_ORIGINS:
        block, sample = build_origin_block(origin, seen_set, new_keys)
        if block:
            blocks.append(block)
            all_sample += sample

    if not blocks:
        log("Nothing new to send this run (all current-window links already sent today).")
        return 0

    header = (
        "🎟️ <b>GoWild matches — bookable right now</b>\n"
        f"{_fmt(date.today())} · origins: <b>{esc('/'.join(MY_ORIGINS))}</b>\n"
        "Tap a city to open the exact Frontier search — logged into your GoWild "
        "account you'll see the live GoWild fare &amp; seats, then book.\n"
        "<i>Domestic confirms the day before departure; international opens 10 days out. "
        "GoWild legs book one-way. ⚠️ = GoWild blackout (Peak Day Charge).</i>"
    )
    send_message(header)
    time.sleep(1)

    blurb = best_bet(all_sample[:24])
    if blurb:
        send_message(f"💡 <b>Best bet:</b> {esc(blurb)}")
        time.sleep(1)

    sent = 0
    for block in blocks:
        if send_message(block):
            sent += 1
            time.sleep(1)

    seen["sent"] = list(seen_set) + new_keys
    save_seen(seen)
    log(f"Done. {sent} origin block(s) sent, {len(new_keys)} new links.")
    return 0


def preview() -> int:
    """Print the digest to the console instead of Telegram (dry run, no dedupe,
    no state change)."""
    print(f"GoWild matches — {_fmt(date.today())} · origins: {'/'.join(MY_ORIGINS)}")
    for origin in MY_ORIGINS:
        block, sample = build_origin_block(origin, set(), [])
        if block:
            # strip HTML tags roughly for console readability
            import re
            txt = re.sub(r"<[^>]+>", "", block)
            print("\n" + txt)
    return 0


def search_origin(origin: str) -> int:
    """Ad-hoc searchgwp-style fan-out: print one-tap links from ONE origin to
    every Frontier city for today + tomorrow (domestic) and 10-days-out (intl).
    Usage: python gowild_matcher.py --origin LAS"""
    origin = origin.upper()
    print(f"GoWild one-click search from {APT.city(origin)} ({origin})\n")
    for dt in domestic_dates():
        print(f"== Domestic, depart {_fmt(dt)}{' (BLACKOUT)' if APT.is_blackout(dt) else ''} ==")
        for d in ordered_dests(intl=False, origin=origin):
            print(f"  {APT.city(d)} ({d}): {web_link(origin, d, dt)}")
    idt = intl_date()
    print(f"\n== International, depart {_fmt(idt)} (10-day window) ==")
    for d in ordered_dests(intl=True, origin=origin):
        print(f"  {APT.city(d)} ({d}): {web_link(origin, d, idt)}")
    return 0


# ---------------------------------------------------------------------------
# On-demand /search command — a cloud poller (responder.yml, every ~5 min) lets
# you text the bot "/search LAS" and get one-tap GoWild links back, any time,
# not just in the morning digest.
# ---------------------------------------------------------------------------

POLL_OFFSET_FILE = BASE_DIR / "poll_offset.json"

HELP_TEXT = (
    "🎟️ <b>GoWild Matcher — commands</b>\n"
    "• <code>/search PHL</code> — one-tap GoWild links from an airport to every "
    "city bookable now (tomorrow domestic + 10-day international).\n"
    "• <code>/search</code> (no code) — uses your default hub.\n"
    "• <code>/help</code> — this message.\n\n"
    "Tap a city to open the exact Frontier search. Logged into your GoWild "
    "account you'll see the live GoWild fare &amp; seats, then book.\n"
    "<i>Any Frontier airport code works as the origin (e.g. LAS, DEN, MCO, ATL, ORD).</i>"
)


def _chunk_lines(lines: list[str], limit: int = 3800) -> list[str]:
    """Pack lines into messages under Telegram's 4096-char cap."""
    out, buf, size = [], [], 0
    for ln in lines:
        add = len(ln) + 1
        if buf and size + add > limit:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(ln)
        size += add
    if buf:
        out.append("\n".join(buf))
    return out


def build_search_blocks(origin: str) -> list[str]:
    """searchgwp-style on-demand fan-out from ONE origin: tappable links to every
    city bookable now — tomorrow (domestic) + 10-days-out (international).
    Returns a list of message strings (chunked to fit Telegram)."""
    origin = origin.upper()
    tomorrow = date.today() + timedelta(days=1)
    lines = [
        f"🔎 <b>GoWild search — {esc(APT.city(origin))} ({esc(origin)})</b>",
        "Tap a city to open the exact Frontier search — logged into GoWild you'll "
        "see live seats. <i>Legs book one-way; tap → change the date in Frontier "
        "for other days.</i>",
        f"\n📅 <b>Depart tomorrow — {esc(_fmt(tomorrow))}</b>{blackout_tag(tomorrow)}  <i>(domestic, book now)</i>",
    ]
    for d in ordered_dests(intl=False, origin=origin)[:SEARCH_DOMESTIC_CAP]:
        lines.append(f"  • <a href=\"{esc(deep_link(origin, d, tomorrow))}\">{esc(APT.city(d))} ({d})</a>")

    if HAVE_PASSPORT:
        idt = intl_date()
        lines.append(f"\n🌎 <b>International — depart {esc(_fmt(idt))}</b>{blackout_tag(idt)}  <i>(10-day window)</i>")
        for d in ordered_dests(intl=True, origin=origin)[:SEARCH_INTL_CAP]:
            lines.append(f"  • <a href=\"{esc(deep_link(origin, d, idt))}\">{esc(APT.city(d))} ({d})</a>  <i>passport</i>")

    return _chunk_lines(lines)


def _load_offset() -> int:
    if POLL_OFFSET_FILE.exists():
        try:
            return int(json.loads(POLL_OFFSET_FILE.read_text(encoding="utf-8")).get("offset", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return 0


def _save_offset(offset: int) -> None:
    try:
        POLL_OFFSET_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    except OSError as e:
        log(f"WARN could not write poll offset: {e}")


def _reply(chat_id: str, text: str) -> None:
    try:
        requests.post(_tg_api("sendMessage"),
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20).raise_for_status()
    except Exception as e:  # noqa: BLE001
        log(f"WARN reply failed: {e}")


def _known_airport(code: str) -> bool:
    code = code.upper()
    return code in APT.DESTINATIONS or code in APT.US_HUBS


def _handle_command(chat_id: str, text: str) -> None:
    t = text.strip()
    low = t.lower()
    if low in ("/start", "/help", "help", "start"):
        _reply(chat_id, HELP_TEXT)
        return
    if low.startswith("/search") or (len(t) == 3 and t.isalpha()):
        parts = t.split()
        if low.startswith("/search"):
            code = (parts[1] if len(parts) > 1 else (MY_ORIGINS[0] if MY_ORIGINS else "PHL")).upper()
        else:
            code = t.upper()
        if not _known_airport(code):
            hubs = ", ".join(list(APT.US_HUBS)[:10])
            _reply(chat_id, f"🤔 I don't know airport <b>{esc(code)}</b>. Try a Frontier code like: {esc(hubs)}…\nOr just send <code>/help</code>.")
            return
        for block in build_search_blocks(code):
            _reply(chat_id, block)
            time.sleep(0.5)
        return
    # Unknown input — gentle nudge.
    _reply(chat_id, "Send <code>/search PHL</code> (or any Frontier airport code) for one-tap GoWild links, or <code>/help</code>.")


def serve_once() -> int:
    """One poll cycle: fetch new updates since the stored offset, answer any
    commands, persist the new offset. Meant to be run on a schedule (every few
    minutes) by responder.yml so the bot answers even when your PC is off."""
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        log("ERROR token still placeholder.")
        return 1
    offset = _load_offset()
    try:
        r = requests.get(_tg_api("getUpdates"),
                         params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'},
                         timeout=30)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:  # noqa: BLE001
        log(f"WARN getUpdates failed: {e}")
        return 1

    handled, last = 0, offset
    for u in updates:
        last = max(last, u["update_id"] + 1)
        msg = u.get("message") or {}
        text = msg.get("text")
        chat = msg.get("chat", {})
        if text and chat.get("id") is not None:
            _handle_command(str(chat["id"]), text)
            handled += 1
    if last != offset:
        _save_offset(last)
    log(f"serve_once: {len(updates)} update(s), {handled} handled, offset -> {last}")
    return 0


def print_chat_id() -> int:
    """Run with --chatid after messaging your NEW bot to discover the chat id."""
    if "CHANGE-ME" in TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in secrets_local.py first.")
        return 1
    try:
        r = requests.get(_tg_api("getUpdates"), timeout=20)
        r.raise_for_status()
        results = r.json().get("result", [])
        if not results:
            print("No messages found. Send your new bot a message first (press Start), then re-run --chatid.")
            return 1
        ids = {u["message"]["chat"]["id"]: u["message"]["chat"].get("username", "")
               for u in results if "message" in u}
        print("Chat id(s) that have messaged your bot:")
        for cid, uname in ids.items():
            print(f"  {cid}   (@{uname})" if uname else f"  {cid}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Error calling getUpdates: {e}")
        return 1


if __name__ == "__main__":
    if "--chatid" in sys.argv:
        sys.exit(print_chat_id())
    if "--serve-once" in sys.argv:
        sys.exit(serve_once())
    if "--origin" in sys.argv:
        i = sys.argv.index("--origin")
        code = sys.argv[i + 1] if i + 1 < len(sys.argv) else "PHL"
        sys.exit(search_origin(code))
    if "--preview" in sys.argv or "--dry-run" in sys.argv:
        sys.exit(preview())
    sys.exit(main())
