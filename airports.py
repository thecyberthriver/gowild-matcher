"""
airports.py — Frontier Airlines network catalog + GoWild booking data for
gowild_matcher.py.

This is the data the matcher fans out over. It mirrors what searchgwp.com does
under the hood: pick an origin airport and generate a search for every city
Frontier flies to, on the date(s) that are actually inside the GoWild booking
window.

IMPORTANT / honesty note
------------------------
Frontier has no public availability API, and the GoWild *price* only shows once
you're logged into a GoWild account inside Frontier's own site/app. So this bot
does NOT scrape seat counts (that's the paid moat of searchgwp/gopassflights and
it breaks constantly against Frontier's bot protection). Instead it builds a
one-tap deep link straight into each Frontier search, at the right moment in the
booking window, so YOU tap and see the live GoWild seats in your logged-in app.

A deep link to a city Frontier doesn't actually serve from your origin just shows
"no flights available" — harmless. So this catalog can be broad without breaking
anything; verify/extend it against the live route map at
https://www.flyfrontier.com/travel/route-map/ when you want to be exhaustive.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# GoWild booking windows (days before departure the fare can be booked).
# Domestic: confirmable the DAY BEFORE departure. International: up to 10 days
# before. Source: flyfrontier.com GoWild FAQ. Same-day domestic is also usually
# bookable, so we surface today + tomorrow for domestic.
# ---------------------------------------------------------------------------
DOMESTIC_WINDOW_DAYS = 1
INTERNATIONAL_WINDOW_DAYS = 10

# ---------------------------------------------------------------------------
# GoWild blackout dates (no free GoWild travel — a Peak Day Charge applies).
# 2026 Fall/Winter pass season. RE-VERIFY on
# https://www.flyfrontier.com/deals/gowild-pass/ — Frontier updates these.
# {(year, month): {days...}}
# ---------------------------------------------------------------------------
BLACKOUT_DATES = {
    (2026, 10): {8, 9, 11, 12},
    (2026, 11): {24, 25, 28, 29, 30},
    (2026, 12): set(range(19, 32)),          # 19-31 (whole holiday stretch)
    (2027, 1):  {1, 2, 3, 14, 15, 18},
    (2027, 2):  {11, 12, 15},
    (2027, 3):  {12, 13, 14, 20, 21, 26, 27, 28, 29},
    (2027, 4):  {2, 3, 4},
}


def is_blackout(d: date) -> bool:
    """True if `d` is a GoWild blackout date (Peak Day Charge applies)."""
    return d.day in BLACKOUT_DATES.get((d.year, d.month), set())


# ---------------------------------------------------------------------------
# Frontier US hubs / focus cities — the airports you can pick as an ORIGIN.
# code -> (city label, region). These are the biggest Frontier stations; the
# matcher's MY_ORIGINS defaults to your home airports but can be set to any of
# these (or all of them).
# ---------------------------------------------------------------------------
US_HUBS = {
    "DEN": ("Denver", "Mountain West"),          # main hub
    "MCO": ("Orlando", "Florida"),
    "LAS": ("Las Vegas", "Southwest"),
    "PHL": ("Philadelphia", "Northeast"),        # your workhorse hub
    "ATL": ("Atlanta", "Southeast"),
    "PHX": ("Phoenix", "Southwest"),
    "ORD": ("Chicago O'Hare", "Midwest"),
    "MIA": ("Miami", "Florida"),
    "TPA": ("Tampa", "Florida"),
    "CLE": ("Cleveland", "Midwest"),
    "CVG": ("Cincinnati", "Midwest"),
    "DFW": ("Dallas–Fort Worth", "South Central"),
    "TTN": ("Trenton", "Northeast"),
    "SJU": ("San Juan", "Puerto Rico"),          # US territory, no passport
    "EWR": ("Newark", "Northeast"),
    "LGA": ("New York LaGuardia", "Northeast"),
    "JFK": ("New York JFK", "Northeast"),
}

# Your home departure airports (where you can realistically start a trip). The
# matcher watches these by default. To watch every Frontier US hub instead, set
#   MY_ORIGINS = list(US_HUBS)
# in gowild_matcher.py.
HOME_HUBS = ["PHL", "EWR", "LGA", "JFK"]

# ---------------------------------------------------------------------------
# Destinations Frontier serves. `intl=True` => passport + 10-day booking window;
# otherwise domestic (incl. Puerto Rico / USVI, which need NO passport) => 1-day
# window. This is a broad, well-known subset of Frontier's ~90-airport US map
# plus its Caribbean / Mexico / Latin America network. Unserved origin->dest
# pairs simply show "no flights" when tapped, so breadth is safe.
# code: (city, region, intl)
# ---------------------------------------------------------------------------
DESTINATIONS = {
    # --- Northeast ---
    "PHL": ("Philadelphia", "Northeast", False),
    "EWR": ("Newark", "Northeast", False),
    "LGA": ("New York LaGuardia", "Northeast", False),
    "JFK": ("New York JFK", "Northeast", False),
    "ISP": ("Long Island / Islip", "Northeast", False),
    "BOS": ("Boston", "Northeast", False),
    "PVD": ("Providence", "Northeast", False),
    "BDL": ("Hartford", "Northeast", False),
    "PIT": ("Pittsburgh", "Northeast", False),
    "BUF": ("Buffalo", "Northeast", False),
    "TTN": ("Trenton", "Northeast", False),
    "BWI": ("Baltimore", "Mid-Atlantic", False),
    "IAD": ("Washington Dulles", "Mid-Atlantic", False),
    "DCA": ("Washington Reagan", "Mid-Atlantic", False),
    "RIC": ("Richmond", "Mid-Atlantic", False),
    "ORF": ("Norfolk", "Mid-Atlantic", False),
    # --- Southeast ---
    "ATL": ("Atlanta", "Southeast", False),
    "CLT": ("Charlotte", "Southeast", False),
    "RDU": ("Raleigh–Durham", "Southeast", False),
    "GSO": ("Greensboro", "Southeast", False),
    "MYR": ("Myrtle Beach", "Southeast", False),
    "CHS": ("Charleston", "Southeast", False),
    "SAV": ("Savannah", "Southeast", False),
    "BNA": ("Nashville", "Southeast", False),
    "TYS": ("Knoxville", "Southeast", False),
    "MEM": ("Memphis", "Southeast", False),
    "BHM": ("Birmingham", "Southeast", False),
    "HSV": ("Huntsville", "Southeast", False),
    # --- Florida ---
    "MCO": ("Orlando", "Florida", False),
    "MIA": ("Miami", "Florida", False),
    "FLL": ("Fort Lauderdale", "Florida", False),
    "TPA": ("Tampa", "Florida", False),
    "RSW": ("Fort Myers", "Florida", False),
    "PBI": ("West Palm Beach", "Florida", False),
    "JAX": ("Jacksonville", "Florida", False),
    "PNS": ("Pensacola", "Florida", False),
    "SRQ": ("Sarasota", "Florida", False),
    "VPS": ("Destin / Fort Walton", "Florida", False),
    # --- Midwest ---
    "ORD": ("Chicago O'Hare", "Midwest", False),
    "MDW": ("Chicago Midway", "Midwest", False),
    "DTW": ("Detroit", "Midwest", False),
    "CLE": ("Cleveland", "Midwest", False),
    "CMH": ("Columbus", "Midwest", False),
    "CVG": ("Cincinnati", "Midwest", False),
    "IND": ("Indianapolis", "Midwest", False),
    "MKE": ("Milwaukee", "Midwest", False),
    "MSP": ("Minneapolis–St. Paul", "Midwest", False),
    "STL": ("St. Louis", "Midwest", False),
    "MCI": ("Kansas City", "Midwest", False),
    "OMA": ("Omaha", "Midwest", False),
    "DSM": ("Des Moines", "Midwest", False),
    "GRR": ("Grand Rapids", "Midwest", False),
    # --- South Central ---
    "DFW": ("Dallas–Fort Worth", "South Central", False),
    "AUS": ("Austin", "South Central", False),
    "SAT": ("San Antonio", "South Central", False),
    "IAH": ("Houston", "South Central", False),
    "MSY": ("New Orleans", "South Central", False),
    "OKC": ("Oklahoma City", "South Central", False),
    "ELP": ("El Paso", "South Central", False),
    # --- Mountain / West ---
    "DEN": ("Denver", "Mountain West", False),
    "LAS": ("Las Vegas", "Southwest", False),
    "PHX": ("Phoenix", "Southwest", False),
    "SLC": ("Salt Lake City", "Mountain West", False),
    "ABQ": ("Albuquerque", "Southwest", False),
    "TUS": ("Tucson", "Southwest", False),
    "COS": ("Colorado Springs", "Mountain West", False),
    "BZN": ("Bozeman", "Mountain West", False),
    "GEG": ("Spokane", "Pacific Northwest", False),
    # --- West Coast ---
    "LAX": ("Los Angeles", "West Coast", False),
    "SAN": ("San Diego", "West Coast", False),
    "SFO": ("San Francisco", "West Coast", False),
    "SJC": ("San Jose CA", "West Coast", False),
    "ONT": ("Ontario CA", "West Coast", False),
    "SNA": ("Orange County", "West Coast", False),
    "SMF": ("Sacramento", "West Coast", False),
    "OAK": ("Oakland", "West Coast", False),
    "SEA": ("Seattle", "Pacific Northwest", False),
    "PDX": ("Portland OR", "Pacific Northwest", False),
    "PSP": ("Palm Springs", "West Coast", False),
    "RNO": ("Reno", "West Coast", False),
    # --- US territories (NO passport, domestic booking window) ---
    "SJU": ("San Juan", "Puerto Rico", False),
    "STT": ("St. Thomas (USVI)", "US Virgin Islands", False),
    "STX": ("St. Croix (USVI)", "US Virgin Islands", False),
    # --- International (passport, 10-day booking window) ---
    "CUN": ("Cancún", "Mexico", True),
    "SJD": ("Los Cabos", "Mexico", True),
    "PVR": ("Puerto Vallarta", "Mexico", True),
    "GDL": ("Guadalajara", "Mexico", True),
    "NAS": ("Nassau", "Bahamas", True),
    "MBJ": ("Montego Bay", "Jamaica", True),
    "KIN": ("Kingston", "Jamaica", True),
    "PUJ": ("Punta Cana", "Dominican Republic", True),
    "SDQ": ("Santo Domingo", "Dominican Republic", True),
    "STI": ("Santiago (DR)", "Dominican Republic", True),
    "AUA": ("Aruba", "Aruba", True),
    "SJO": ("San José", "Costa Rica", True),
    "LIR": ("Liberia", "Costa Rica", True),
    "SAL": ("San Salvador", "El Salvador", True),
    "GUA": ("Guatemala City", "Guatemala", True),
    "BOG": ("Bogotá", "Colombia", True),
    "CTG": ("Cartagena", "Colombia", True),
    "MDE": ("Medellín", "Colombia", True),
}

# A short, high-appeal set the digest leads with when rotating (keeps the first
# links you see interesting). Everything else still rotates in over subsequent
# days. Purely cosmetic ordering, not a filter.
POPULAR = [
    "MCO", "LAS", "MIA", "FLL", "TPA", "ATL", "DEN", "ORD", "LAX", "NAS",
    "CUN", "SJU", "MBJ", "PUJ", "AUA", "BNA", "MSY", "CHS", "SAV", "RSW",
]


def city(code: str) -> str:
    """Human label for an airport code (falls back to the code)."""
    if code in DESTINATIONS:
        return DESTINATIONS[code][0]
    if code in US_HUBS:
        return US_HUBS[code][0]
    return code


def region(code: str) -> str:
    if code in DESTINATIONS:
        return DESTINATIONS[code][1]
    if code in US_HUBS:
        return US_HUBS[code][1]
    return ""


def is_international(code: str) -> bool:
    """True if the destination needs a passport (=> 10-day GoWild window)."""
    return bool(DESTINATIONS.get(code, ("", "", False))[2])


def all_destinations(exclude: set[str] | None = None) -> list[str]:
    """All destination codes, minus any in `exclude` (e.g. the origin itself)."""
    exclude = exclude or set()
    return [c for c in DESTINATIONS if c not in exclude]
