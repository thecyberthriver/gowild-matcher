/**
 * GoWild Matcher — Cloudflare Worker (instant Telegram webhook).
 *
 * Answers /search and /help the moment you send them (no 5-min poll). Telegram
 * POSTs each update to this Worker; we build searchgwp-style one-tap GoWild links
 * and reply immediately.
 *
 * Mirrors the /search logic in gowild_matcher.py (web-mode https links). Frontier
 * has no public API and the GoWild fare only shows when you're logged into GoWild,
 * so we hand you the exact pre-filled search — your Frontier app/site shows live
 * seats on tap.
 *
 * Bindings (set via wrangler / dashboard):
 *   - TELEGRAM_BOT_TOKEN  (secret)  bot token
 *   - WEBHOOK_SECRET      (secret)  matches Telegram's setWebhook secret_token
 *   - OWNER_CHAT_ID       (var)     optional; if set, only this chat is answered
 */

// --- Catalog (ported from airports.py) --------------------------------------
// code -> [city, intl?]  (intl=1 => passport + 10-day window; else domestic)
const D = {
  // Northeast / Mid-Atlantic
  PHL: ["Philadelphia", 0], EWR: ["Newark", 0], LGA: ["New York LaGuardia", 0],
  JFK: ["New York JFK", 0], ISP: ["Long Island / Islip", 0], BOS: ["Boston", 0],
  PVD: ["Providence", 0], BDL: ["Hartford", 0], PIT: ["Pittsburgh", 0],
  BUF: ["Buffalo", 0], TTN: ["Trenton", 0], BWI: ["Baltimore", 0],
  IAD: ["Washington Dulles", 0], DCA: ["Washington Reagan", 0], RIC: ["Richmond", 0],
  ORF: ["Norfolk", 0],
  // Southeast
  ATL: ["Atlanta", 0], CLT: ["Charlotte", 0], RDU: ["Raleigh–Durham", 0],
  GSO: ["Greensboro", 0], MYR: ["Myrtle Beach", 0], CHS: ["Charleston", 0],
  SAV: ["Savannah", 0], BNA: ["Nashville", 0], TYS: ["Knoxville", 0],
  MEM: ["Memphis", 0], BHM: ["Birmingham", 0], HSV: ["Huntsville", 0],
  // Florida
  MCO: ["Orlando", 0], MIA: ["Miami", 0], FLL: ["Fort Lauderdale", 0],
  TPA: ["Tampa", 0], RSW: ["Fort Myers", 0], PBI: ["West Palm Beach", 0],
  JAX: ["Jacksonville", 0], PNS: ["Pensacola", 0], SRQ: ["Sarasota", 0],
  VPS: ["Destin / Fort Walton", 0],
  // Midwest
  ORD: ["Chicago O'Hare", 0], MDW: ["Chicago Midway", 0], DTW: ["Detroit", 0],
  CLE: ["Cleveland", 0], CMH: ["Columbus", 0], CVG: ["Cincinnati", 0],
  IND: ["Indianapolis", 0], MKE: ["Milwaukee", 0], MSP: ["Minneapolis–St. Paul", 0],
  STL: ["St. Louis", 0], MCI: ["Kansas City", 0], OMA: ["Omaha", 0],
  DSM: ["Des Moines", 0], GRR: ["Grand Rapids", 0],
  // South Central
  DFW: ["Dallas–Fort Worth", 0], AUS: ["Austin", 0], SAT: ["San Antonio", 0],
  IAH: ["Houston", 0], MSY: ["New Orleans", 0], OKC: ["Oklahoma City", 0],
  ELP: ["El Paso", 0],
  // Mountain / West
  DEN: ["Denver", 0], LAS: ["Las Vegas", 0], PHX: ["Phoenix", 0],
  SLC: ["Salt Lake City", 0], ABQ: ["Albuquerque", 0], TUS: ["Tucson", 0],
  COS: ["Colorado Springs", 0], BZN: ["Bozeman", 0], GEG: ["Spokane", 0],
  // West Coast
  LAX: ["Los Angeles", 0], SAN: ["San Diego", 0], SFO: ["San Francisco", 0],
  SJC: ["San Jose CA", 0], ONT: ["Ontario CA", 0], SNA: ["Orange County", 0],
  SMF: ["Sacramento", 0], OAK: ["Oakland", 0], SEA: ["Seattle", 0],
  PDX: ["Portland OR", 0], PSP: ["Palm Springs", 0], RNO: ["Reno", 0],
  // US territories (no passport)
  SJU: ["San Juan", 0], STT: ["St. Thomas (USVI)", 0], STX: ["St. Croix (USVI)", 0],
  // International (passport, 10-day window)
  CUN: ["Cancún", 1], SJD: ["Los Cabos", 1], PVR: ["Puerto Vallarta", 1],
  GDL: ["Guadalajara", 1], NAS: ["Nassau", 1], MBJ: ["Montego Bay", 1],
  KIN: ["Kingston", 1], PUJ: ["Punta Cana", 1], SDQ: ["Santo Domingo", 1],
  STI: ["Santiago (DR)", 1], AUA: ["Aruba", 1], SJO: ["San José", 1],
  LIR: ["Liberia", 1], SAL: ["San Salvador", 1], GUA: ["Guatemala City", 1],
  BOG: ["Bogotá", 1], CTG: ["Cartagena", 1], MDE: ["Medellín", 1],
};

const POPULAR = ["MCO","LAS","MIA","FLL","TPA","ATL","DEN","ORD","LAX","NAS",
  "CUN","SJU","MBJ","PUJ","AUA","BNA","MSY","CHS","SAV","RSW"];

// GoWild blackout days by "year-month" (re-verify on flyfrontier.com/deals/gowild-pass)
const BLACKOUT = {
  "2026-10": [8,9,11,12], "2026-11": [24,25,28,29,30],
  "2026-12": Array.from({length:13},(_,i)=>19+i), // 19..31
  "2027-1": [1,2,3,14,15,18], "2027-2": [11,12,15],
  "2027-3": [12,13,14,20,21,26,27,28,29], "2027-4": [2,3,4],
};

const SEARCH_DOMESTIC_CAP = 16;
const SEARCH_INTL_CAP = 8;
const INTL_WINDOW_DAYS = 10;
const DEFAULT_ORIGIN = "PHL";

const WD = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

// --- helpers ----------------------------------------------------------------
const esc = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const city = (c) => (D[c] ? D[c][0] : c);
const isIntl = (c) => !!(D[c] && D[c][1]);
const known = (c) => Object.prototype.hasOwnProperty.call(D, c);

// "today" on the US East-coast calendar, as a UTC-midnight Date for that day.
function todayET() {
  const p = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const g = (t) => +p.find((x) => x.type === t).value;
  return new Date(Date.UTC(g("year"), g("month") - 1, g("day")));
}
const addDays = (d, n) => new Date(d.getTime() + n * 86400000);
const ymd = (d) => `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}-${String(d.getUTCDate()).padStart(2,"0")}`;
const fmt = (d) => `${WD[d.getUTCDay()]} ${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;

function isBlackout(d) {
  const key = `${d.getUTCFullYear()}-${d.getUTCMonth()+1}`;
  return (BLACKOUT[key] || []).includes(d.getUTCDate());
}
const blackoutTag = (d) => (isBlackout(d) ? " ⚠️<i>blackout</i>" : "");

function webLink(o, dcode, d) {
  return "https://booking.flyfrontier.com/Flight/InternalSelect" +
    `?o1=${o}&d1=${dcode}&dd1=${ymd(d)}&ADT=1&mon=true`;
}

function orderedDests(intl, origin) {
  const pool = Object.keys(D).filter((c) => c !== origin && isIntl(c) === !!intl);
  const pop = POPULAR.filter((c) => pool.includes(c));
  const rest = pool.filter((c) => !pop.includes(c));
  return pop.concat(rest);
}

function chunk(lines, limit = 3800) {
  const out = []; let buf = [], size = 0;
  for (const ln of lines) {
    const add = ln.length + 1;
    if (buf.length && size + add > limit) { out.push(buf.join("\n")); buf = []; size = 0; }
    buf.push(ln); size += add;
  }
  if (buf.length) out.push(buf.join("\n"));
  return out;
}

function buildSearchBlocks(origin) {
  origin = origin.toUpperCase();
  const today = todayET();
  const tomorrow = addDays(today, 1);
  const idt = addDays(today, INTL_WINDOW_DAYS);
  const lines = [
    `🔎 <b>GoWild search — ${esc(city(origin))} (${esc(origin)})</b>`,
    "Tap a city to open the exact Frontier search — logged into GoWild you'll " +
      "see live seats. <i>Legs book one-way; tap → change the date in Frontier " +
      "for other days.</i>",
    `\n📅 <b>Depart tomorrow — ${esc(fmt(tomorrow))}</b>${blackoutTag(tomorrow)}  <i>(domestic, book now)</i>`,
  ];
  for (const c of orderedDests(0, origin).slice(0, SEARCH_DOMESTIC_CAP)) {
    lines.push(`  • <a href="${esc(webLink(origin, c, tomorrow))}">${esc(city(c))} (${c})</a>`);
  }
  lines.push(`\n🌎 <b>International — depart ${esc(fmt(idt))}</b>${blackoutTag(idt)}  <i>(10-day window)</i>`);
  for (const c of orderedDests(1, origin).slice(0, SEARCH_INTL_CAP)) {
    lines.push(`  • <a href="${esc(webLink(origin, c, idt))}">${esc(city(c))} (${c})</a>  <i>passport</i>`);
  }
  return chunk(lines);
}

const HELP = "🎟️ <b>GoWild Matcher — commands</b>\n" +
  "• <code>/search PHL</code> — one-tap GoWild links from an airport to every " +
  "city bookable now (tomorrow domestic + 10-day international).\n" +
  "• <code>/search</code> (no code) — uses the default hub.\n" +
  "• <code>/help</code> — this message.\n\n" +
  "Tap a city to open the exact Frontier search. Logged into your GoWild account " +
  "you'll see the live GoWild fare &amp; seats, then book.\n" +
  "<i>Any Frontier airport code works (e.g. LAS, DEN, MCO, ATL, ORD).</i>";

async function tgSend(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML",
      disable_web_page_preview: true }),
  });
}

async function handleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.text || !msg.chat) return;
  const chatId = msg.chat.id;
  // Optional owner lock.
  if (env.OWNER_CHAT_ID && String(chatId) !== String(env.OWNER_CHAT_ID)) return;

  const t = msg.text.trim();
  const low = t.toLowerCase();

  if (["/start","/help","help","start"].includes(low)) {
    await tgSend(env, chatId, HELP);
    return;
  }
  if (low.startsWith("/search") || (t.length === 3 && /^[a-zA-Z]{3}$/.test(t))) {
    let code;
    if (low.startsWith("/search")) {
      const parts = t.split(/\s+/);
      code = (parts[1] || DEFAULT_ORIGIN).toUpperCase();
    } else {
      code = t.toUpperCase();
    }
    if (!known(code)) {
      await tgSend(env, chatId, `🤔 I don't know airport <b>${esc(code)}</b>. Try a Frontier code like: PHL, LAS, DEN, MCO, ATL, ORD…\nOr send <code>/help</code>.`);
      return;
    }
    for (const block of buildSearchBlocks(code)) {
      await tgSend(env, chatId, block);
    }
    return;
  }
  await tgSend(env, chatId, "Send <code>/search PHL</code> (or any Frontier airport code) for one-tap GoWild links, or <code>/help</code>.");
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("GoWild Matcher webhook is up.", { status: 200 });
    }
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }
    // Verify Telegram's secret header.
    if (env.WEBHOOK_SECRET &&
        request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 401 });
    }
    let update;
    try { update = await request.json(); }
    catch { return new Response("bad request", { status: 400 }); }

    // Answer in the background; ack Telegram immediately so it doesn't retry.
    ctx.waitUntil(handleUpdate(env, update).catch((e) => console.log("handle error", e)));
    return new Response("ok", { status: 200 });
  },
};
