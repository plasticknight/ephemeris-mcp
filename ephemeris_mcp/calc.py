"""Chart calculations on top of the Swiss Ephemeris.

Everything here is a plain function: birth details in, numbers out. Nothing
is stored and nothing is fetched from the network, so the same input always
gives the same answer.

Conventions (Parashari unless stated):
- Zodiac: sidereal by default, Lahiri ayanamsa.
- Nodes: mean by default; Ketu is exactly opposite Rahu.
- Houses: whole sign by default.
- Vimshottari: 120-year cycle from the Moon's nakshatra, 365.25-day year
  by default.
- Divisional charts: the classical Parashari rules for each division.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

# ---------------------------------------------------------------- reference

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
RASHIS = ["Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
          "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"]
SIGN_LORDS = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
              "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter"]

NAKSHATRAS = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
              "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
              "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
              "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
              "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada",
              "Revati"]
NAK_SPAN = 360.0 / 27.0

# Vimshottari order, starting from Ashwini's lord, with years.
DASHA_ORDER = [("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10), ("Mars", 7),
               ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17)]
DASHA_YEARS = dict(DASHA_ORDER)
DASHA_LORDS = [lord for lord, _ in DASHA_ORDER]

AYANAMSAS = {
    "lahiri": swe.SIDM_LAHIRI,
    "lahiri_icrc": swe.SIDM_LAHIRI_ICRC,
    "raman": swe.SIDM_RAMAN,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
    "true_chitra": swe.SIDM_TRUE_CITRA,
    "yukteshwar": swe.SIDM_YUKTESHWAR,
    "fagan_bradley": swe.SIDM_FAGAN_BRADLEY,
}

HOUSE_SYSTEMS = {
    "whole_sign": b"W",
    "sripati": b"S",
    "placidus": b"P",
    "koch": b"K",
    "equal": b"E",
    "porphyry": b"O",
}

CLASSICAL = [("Sun", swe.SUN), ("Moon", swe.MOON), ("Mars", swe.MARS),
             ("Mercury", swe.MERCURY), ("Jupiter", swe.JUPITER),
             ("Venus", swe.VENUS), ("Saturn", swe.SATURN)]
OUTER = [("Uranus", swe.URANUS), ("Neptune", swe.NEPTUNE), ("Pluto", swe.PLUTO)]

SUPPORTED_DIVISIONS = [1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]
DIVISION_NAMES = {
    1: "Rashi", 2: "Hora", 3: "Drekkana", 4: "Chaturthamsha", 7: "Saptamsha",
    9: "Navamsha", 10: "Dashamsha", 12: "Dwadashamsha", 16: "Shodashamsha",
    20: "Vimshamsha", 24: "Chaturvimshamsha", 27: "Bhamsha", 30: "Trimshamsha",
    40: "Khavedamsha", 45: "Akshavedamsha", 60: "Shashtyamsha",
}


class ChartError(ValueError):
    """Bad input, explained in words the caller can act on."""


# ------------------------------------------------------------------- input

@dataclass
class Moment:
    local: datetime          # as given, with the offset actually used
    utc: datetime
    jd_ut: float
    offset_source: str       # "utc_offset" or the IANA zone name


_OFFSET = re.compile(r"^([+-])(\d{1,2}):?(\d{2})(?::?(\d{2}))?$")


def parse_offset(text: str) -> timedelta:
    m = _OFFSET.match(text.strip())
    if not m:
        raise ChartError(f'utc_offset "{text}" is not understood; write it like "+05:30" or "-04:00"')
    sign = -1 if m.group(1) == "-" else 1
    hours, minutes, seconds = int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    if hours > 14 or minutes > 59 or seconds > 59:
        raise ChartError(f'utc_offset "{text}" is out of range')
    return sign * timedelta(hours=hours, minutes=minutes, seconds=seconds)


def moment(date: str, time: str, utc_offset: str | None = None, timezone: str | None = None) -> Moment:
    """Turn a local birth date and time into Universal Time.

    Exactly one of utc_offset ("+05:30") or timezone ("Asia/Kolkata") must be
    given. A zone name applies the historical rules for that date (war time,
    old local-mean-time offsets), which is often right and occasionally not
    what the birth record meant -- so the offset used is always reported.
    """
    if bool(utc_offset) == bool(timezone):
        raise ChartError("give exactly one of utc_offset (like \"+05:30\") or timezone (like \"Asia/Kolkata\")")
    try:
        naive = datetime.fromisoformat(f"{date.strip()}T{time.strip()}")
    except ValueError:
        raise ChartError(f'date "{date}" / time "{time}" not understood; use YYYY-MM-DD and HH:MM or HH:MM:SS (24-hour)')
    if naive.tzinfo is not None:
        raise ChartError("put the offset in utc_offset or timezone, not inside the time")

    if timezone:
        try:
            zone = ZoneInfo(timezone.strip())
        except (ZoneInfoNotFoundError, ValueError):
            raise ChartError(f'timezone "{timezone}" is not a known zone name; use one like "Asia/Kolkata" or "Europe/London"')
        local = naive.replace(tzinfo=zone)
        source = timezone.strip()
    else:
        local = naive.replace(tzinfo=dt_timezone(parse_offset(utc_offset)))
        source = "utc_offset"

    utc = local.astimezone(dt_timezone.utc)
    hours = utc.hour + utc.minute / 60 + (utc.second + utc.microsecond / 1e6) / 3600
    jd = swe.julday(utc.year, utc.month, utc.day, hours, swe.GREG_CAL)
    return Moment(local=local, utc=utc, jd_ut=jd, offset_source=source)


def check_place(latitude: float | None, longitude: float | None, required: bool) -> None:
    if latitude is None or longitude is None:
        if required:
            raise ChartError("latitude and longitude are needed for the ascendant and houses (decimal degrees; north and east positive)")
        return
    if not -90 <= latitude <= 90:
        raise ChartError(f"latitude {latitude} is outside -90..90")
    if not -180 <= longitude <= 180:
        raise ChartError(f"longitude {longitude} is outside -180..180 (east is positive)")


# ------------------------------------------------------------ ephemeris setup

def _ephemeris_flags() -> int:
    # Ask for the Swiss files; if they are not installed the library falls
    # back to its built-in Moshier model and says so in the return flags,
    # which is reported back so nobody mistakes one for the other.
    path = os.environ.get("SE_EPHE_PATH", "").strip()
    if path:
        swe.set_ephe_path(path)
    return swe.FLG_SWIEPH | swe.FLG_SPEED


def _mode_used(retflags: int) -> str:
    if retflags & swe.FLG_MOSEPH:
        return "Moshier (built in; about 1 arc-second, fine for charts)"
    return "Swiss Ephemeris data files"


def _sidereal(ayanamsa: str) -> int:
    key = (ayanamsa or "lahiri").strip().lower()
    if key not in AYANAMSAS:
        raise ChartError(f'ayanamsa "{ayanamsa}" is not supported; choose one of: {", ".join(AYANAMSAS)}')
    swe.set_sid_mode(AYANAMSAS[key], 0, 0)
    return swe.FLG_SIDEREAL


# ----------------------------------------------------------------- helpers

def dms(deg: float) -> str:
    """15.396 -> 15°23'46\""""
    total = round(deg * 3600)
    d, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{d}°{m:02d}'{s:02d}\""


def sign_index(lon: float) -> int:
    return int((lon % 360.0) // 30.0) % 12


def nakshatra(lon: float) -> dict:
    lon %= 360.0
    idx = min(int(lon // NAK_SPAN), 26)
    into = lon - idx * NAK_SPAN
    pada = min(int(into // (NAK_SPAN / 4)) + 1, 4)
    return {"nakshatra": NAKSHATRAS[idx], "number": idx + 1, "pada": pada,
            "lord": DASHA_LORDS[idx % 9]}


def describe(lon: float, sidereal: bool) -> dict:
    lon %= 360.0
    s = sign_index(lon)
    out = {
        "longitude": round(lon, 6),
        "sign": SIGNS[s],
        "rashi": RASHIS[s],
        "sign_lord": SIGN_LORDS[s],
        "degree_in_sign": round(lon - s * 30, 6),
        "position": f"{dms(lon - s * 30)} {SIGNS[s]}",
    }
    if sidereal:
        out.update(nakshatra(lon))
    return out


def _settings(m: Moment, zodiac: str, ayanamsa: str | None, aya_value: float | None, mode: str, node: str, extra: dict | None = None) -> dict:
    s = {
        "local_time": m.local.isoformat(),
        "utc_offset_used": _fmt_offset(m.local.utcoffset()),
        "offset_from": m.offset_source,
        "utc": m.utc.isoformat().replace("+00:00", "Z"),
        "julian_day_ut": round(m.jd_ut, 6),
        "zodiac": zodiac,
        "nodes": node,
        "ephemeris": mode,
    }
    if zodiac == "sidereal":
        s["ayanamsa"] = ayanamsa
        s["ayanamsa_value"] = f"{dms(aya_value)} ({aya_value:.6f}°)"
    if extra:
        s.update(extra)
    return s


def _fmt_offset(td: timedelta | None) -> str:
    secs = int((td or timedelta()).total_seconds())
    sign = "-" if secs < 0 else "+"
    secs = abs(secs)
    h, rem = divmod(secs, 3600)
    mnt, sec = divmod(rem, 60)
    return f"{sign}{h:02d}:{mnt:02d}" + (f":{sec:02d}" if sec else "")


# --------------------------------------------------------------- positions

def _positions(m: Moment, zodiac: str, ayanamsa: str, node: str, include_outer: bool):
    zodiac = (zodiac or "sidereal").strip().lower()
    if zodiac not in ("sidereal", "tropical"):
        raise ChartError('zodiac must be "sidereal" or "tropical"')
    node = (node or "mean").strip().lower()
    if node not in ("mean", "true"):
        raise ChartError('node must be "mean" or "true"')

    flags = _ephemeris_flags()
    aya_value = None
    if zodiac == "sidereal":
        flags |= _sidereal(ayanamsa)
        _, aya_value = swe.get_ayanamsa_ex_ut(m.jd_ut, flags & ~swe.FLG_SIDEREAL & ~swe.FLG_SPEED)

    bodies = CLASSICAL + (OUTER if include_outer else [])
    rows, mode = {}, None
    try:
        for name, body in bodies:
            xx, ret = swe.calc_ut(m.jd_ut, body, flags)
            mode = mode or _mode_used(ret)
            rows[name] = _body(xx, zodiac == "sidereal")
        xx, ret = swe.calc_ut(m.jd_ut, swe.MEAN_NODE if node == "mean" else swe.TRUE_NODE, flags)
        rows["Rahu"] = _body(xx, zodiac == "sidereal")
        ketu = list(xx)
        ketu[0] = (xx[0] + 180.0) % 360.0
        rows["Ketu"] = _body(ketu, zodiac == "sidereal")
    except swe.Error as err:
        raise ChartError(f"the ephemeris could not compute this date: {err}. The built-in model covers roughly 3000 BC to AD 3000.")
    return rows, zodiac, node, aya_value, mode


def _body(xx, sidereal: bool) -> dict:
    out = describe(xx[0], sidereal)
    out["speed_deg_per_day"] = round(xx[3], 6)
    out["retrograde"] = xx[3] < 0
    return out


def planet_positions(date, time, utc_offset=None, timezone=None, zodiac="sidereal",
                     ayanamsa="lahiri", node="mean", include_outer=False) -> dict:
    m = moment(date, time, utc_offset, timezone)
    rows, zodiac, node, aya, mode = _positions(m, zodiac, ayanamsa, node, include_outer)
    return {"settings": _settings(m, zodiac, ayanamsa, aya, mode, node), "planets": rows}


# ------------------------------------------------------------------ houses

def _ascendant(m: Moment, latitude: float, longitude: float, zodiac: str, ayanamsa: str, house_system: str):
    hs_key = (house_system or "whole_sign").strip().lower()
    if hs_key not in HOUSE_SYSTEMS:
        raise ChartError(f'house_system "{house_system}" is not supported; choose one of: {", ".join(HOUSE_SYSTEMS)}')
    flags = 0
    if zodiac == "sidereal":
        flags |= _sidereal(ayanamsa)
    try:
        cusps, ascmc = swe.houses_ex(m.jd_ut, latitude, longitude, HOUSE_SYSTEMS[hs_key], flags)
    except swe.Error:
        raise ChartError(f"{hs_key} houses cannot be drawn at latitude {latitude} (near the poles some ecliptic degrees never rise). Use whole_sign, equal or porphyry.")
    return hs_key, list(cusps)[:12], ascmc[0], ascmc[1]


def house_of(lon: float, lagna: float, cusps: list[float], system: str) -> int:
    if system == "whole_sign":
        return (sign_index(lon) - sign_index(lagna)) % 12 + 1
    lon %= 360.0
    for i in range(12):
        start, end = cusps[i] % 360.0, cusps[(i + 1) % 12] % 360.0
        span = (end - start) % 360.0
        if (lon - start) % 360.0 < span:
            return i + 1
    return 12  # only reachable through rounding at a cusp


def ascendant_and_houses(date, time, latitude, longitude, utc_offset=None, timezone=None,
                         zodiac="sidereal", ayanamsa="lahiri", node="mean",
                         house_system="whole_sign", include_outer=False) -> dict:
    check_place(latitude, longitude, required=True)
    m = moment(date, time, utc_offset, timezone)
    rows, zodiac, node, aya, mode = _positions(m, zodiac, ayanamsa, node, include_outer)
    system, cusps, asc, mc = _ascendant(m, latitude, longitude, zodiac, ayanamsa, house_system)

    for row in rows.values():
        row["house"] = house_of(row["longitude"], asc, cusps, system)
    houses = []
    for i in range(12):
        h = {"house": i + 1, "cusp": describe(cusps[i], False)["position"], "cusp_longitude": round(cusps[i] % 360, 6)}
        if system == "whole_sign":
            s = (sign_index(asc) + i) % 12
            h.update({"sign": SIGNS[s], "rashi": RASHIS[s], "sign_lord": SIGN_LORDS[s]})
        h["occupants"] = [n for n, r in rows.items() if r["house"] == i + 1]
        houses.append(h)

    return {
        "settings": _settings(m, zodiac, ayanamsa, aya, mode, node,
                              {"house_system": system, "latitude": latitude, "longitude": longitude}),
        "ascendant": describe(asc, zodiac == "sidereal"),
        "midheaven": describe(mc, zodiac == "sidereal"),
        "houses": houses,
        "planets": rows,
    }


# ------------------------------------------------------------- vimshottari

def _add_years(start: datetime, years: float, year_days: float) -> datetime:
    return start + timedelta(days=years * year_days)


def _subperiods(lord: str, start: datetime, total_years: float, year_days: float):
    """The nine sub-periods of a period ruled by `lord`, starting with it."""
    i = DASHA_LORDS.index(lord)
    out, t = [], start
    for k in range(9):
        sub = DASHA_LORDS[(i + k) % 9]
        yrs = total_years * DASHA_YEARS[sub] / 120.0
        end = _add_years(t, yrs, year_days)
        out.append((sub, t, end, yrs))
        t = end
    return out


def _span(lord, start, end, years):
    return {"lord": lord, "start": start.date().isoformat(), "end": end.date().isoformat(),
            "years": round(years, 4)}


def _ymd(years: float, year_days: float) -> str:
    days_total = years * year_days
    y = int(years)
    rem_days = days_total - y * year_days
    mo = int(rem_days // (year_days / 12))
    d = int(round(rem_days - mo * (year_days / 12)))
    return f"{y}y {mo}m {d}d"


def vimshottari_dasha(date, time, utc_offset=None, timezone=None, ayanamsa="lahiri",
                      levels=2, on_date=None, year_days=365.25) -> dict:
    if levels not in (1, 2, 3):
        raise ChartError("levels must be 1 (mahadasha), 2 (+ antardasha) or 3 (+ pratyantardasha for the current antardasha)")
    if not 360 <= float(year_days) <= 366:
        raise ChartError("year_days must be between 360 and 366 (365.25 is usual; 360 is the savana year)")
    year_days = float(year_days)

    m = moment(date, time, utc_offset, timezone)
    rows, _, _, aya, mode = _positions(m, "sidereal", ayanamsa, "mean", False)
    moon = rows["Moon"]["longitude"]
    idx = min(int(moon // NAK_SPAN), 26)
    elapsed = (moon - idx * NAK_SPAN) / NAK_SPAN
    first = DASHA_LORDS[idx % 9]
    first_years = DASHA_YEARS[first]

    birth = m.local
    cycle_start = birth - timedelta(days=elapsed * first_years * year_days)
    try:
        when = Date.fromisoformat(on_date) if on_date else datetime.now(dt_timezone.utc).date()
    except ValueError:
        raise ChartError(f'on_date "{on_date}" not understood; use YYYY-MM-DD')

    mahas, t = [], cycle_start
    start_i = DASHA_LORDS.index(first)
    # Two cycles: enough for anyone's life whatever the starting balance.
    for k in range(18):
        lord = DASHA_LORDS[(start_i + k) % 9]
        end = _add_years(t, DASHA_YEARS[lord], year_days)
        mahas.append((lord, t, end, DASHA_YEARS[lord]))
        t = end
        if (t - birth).days > 130 * 365:
            break

    def contains(s, e):
        return s.date() <= when < e.date()

    out_mahas, current = [], {}
    for lord, s, e, yrs in mahas:
        entry = _span(lord, s, e, yrs)
        if s < birth:
            entry["note"] = f"running at birth; balance {_ymd((e - birth).days / year_days, year_days)}"
        if levels >= 2:
            subs = _subperiods(lord, s, yrs, year_days)
            entry["antardashas"] = [_span(*x) for x in subs]
        if contains(s, e):
            current["mahadasha"] = _span(lord, s, e, yrs)
            for sub in _subperiods(lord, s, yrs, year_days):
                if contains(sub[1], sub[2]):
                    current["antardasha"] = _span(*sub)
                    pratys = _subperiods(sub[0], sub[1], sub[3], year_days)
                    for p in pratys:
                        if contains(p[1], p[2]):
                            current["pratyantardasha"] = _span(*p)
                    if levels == 3:
                        current["pratyantardashas"] = [_span(*p) for p in pratys]
        out_mahas.append(entry)

    return {
        "settings": _settings(m, "sidereal", ayanamsa, aya, mode, "mean",
                              {"year_days": year_days, "on_date": when.isoformat(),
                               "dates_are": "local to the birth offset; start dates inclusive"}),
        "moon": {k: rows["Moon"][k] for k in ("position", "nakshatra", "pada", "lord")},
        "balance_at_birth": {"lord": first, "remaining": _ymd((1 - elapsed) * first_years, year_days),
                             "elapsed_fraction": round(elapsed, 6)},
        "current": current,
        "mahadashas": out_mahas,
    }


# ------------------------------------------------------- divisional charts

# Trimshamsha (D30), Parashari: unequal parts ruled by the five non-luminaries.
_D30_ODD = [(5, 0), (10, 10), (18, 8), (25, 2), (30, 6)]    # Aries, Aquarius, Sagittarius, Gemini, Libra
_D30_EVEN = [(5, 1), (12, 5), (20, 11), (25, 9), (30, 7)]   # Taurus, Virgo, Pisces, Capricorn, Scorpio


def varga_sign(lon: float, n: int) -> int:
    """The sign (0 = Aries) a sidereal longitude falls in, in division D-n."""
    if n not in SUPPORTED_DIVISIONS:
        raise ChartError(f"D{n} is not supported; choose from {', '.join('D%d' % d for d in SUPPORTED_DIVISIONS)}")
    lon %= 360.0
    s = sign_index(lon)
    d = lon - s * 30.0
    odd = s % 2 == 0          # Aries, Gemini ... are the odd signs
    quality = s % 3           # 0 movable, 1 fixed, 2 dual
    p = min(int(d // (30.0 / n)), n - 1)

    if n == 1:
        return s
    if n == 2:                # Leo = Sun's hora, Cancer = Moon's
        first, second = (4, 3) if odd else (3, 4)
        return first if d < 15 else second
    if n == 3:                # same, 5th, 9th
        return (s + 4 * p) % 12
    if n == 4:                # same, 4th, 7th, 10th
        return (s + 3 * p) % 12
    if n == 7:                # odd from itself, even from the 7th
        return ((s if odd else s + 6) + p) % 12
    if n == 9:                # fire from Aries, earth Capricorn, air Libra, water Cancer
        return (s * 9 + p) % 12
    if n == 10:               # odd from itself, even from the 9th
        return ((s if odd else s + 8) + p) % 12
    if n == 12:
        return (s + p) % 12
    if n == 16:               # movable Aries, fixed Leo, dual Sagittarius
        return ((0, 4, 8)[quality] + p) % 12
    if n == 20:               # movable Aries, fixed Sagittarius, dual Leo
        return ((0, 8, 4)[quality] + p) % 12
    if n == 24:               # odd from Leo, even from Cancer
        return ((4 if odd else 3) + p) % 12
    if n == 27:               # fire Aries, earth Cancer, air Libra, water Capricorn
        return (s * 27 + p) % 12
    if n == 30:
        for limit, sign in (_D30_ODD if odd else _D30_EVEN):
            if d < limit:
                return sign
        return (_D30_ODD if odd else _D30_EVEN)[-1][1]
    if n == 40:               # odd from Aries, even from Libra
        return ((0 if odd else 6) + p) % 12
    if n == 45:               # movable Aries, fixed Leo, dual Sagittarius
        return ((0, 4, 8)[quality] + p) % 12
    if n == 60:               # counted from the sign itself
        return (s + p) % 12
    raise AssertionError(n)


def divisional_charts(date, time, latitude, longitude, utc_offset=None, timezone=None,
                      ayanamsa="lahiri", node="mean", divisions=(9,)) -> dict:
    check_place(latitude, longitude, required=True)
    divs = sorted({int(x) for x in (divisions or [9])})
    for n in divs:
        if n not in SUPPORTED_DIVISIONS:
            raise ChartError(f"D{n} is not supported; choose from {', '.join('D%d' % d for d in SUPPORTED_DIVISIONS)}")
    m = moment(date, time, utc_offset, timezone)
    rows, _, node, aya, mode = _positions(m, "sidereal", ayanamsa, node, False)
    _, _, asc, _ = _ascendant(m, latitude, longitude, "sidereal", ayanamsa, "whole_sign")

    points = {"Lagna": asc, **{k: v["longitude"] for k, v in rows.items()}}
    charts = {}
    for n in divs:
        lagna_sign = varga_sign(asc, n)
        placements = {}
        for name, lon in points.items():
            vs = varga_sign(lon, n)
            row = {"sign": SIGNS[vs], "rashi": RASHIS[vs],
                   "house": (vs - lagna_sign) % 12 + 1}
            if n == 9 and vs == sign_index(lon):
                row["vargottama"] = True
            placements[name] = row
        charts[f"D{n}"] = {"name": DIVISION_NAMES[n], "lagna": SIGNS[lagna_sign], "placements": placements}

    return {
        "settings": _settings(m, "sidereal", ayanamsa, aya, mode, node,
                              {"latitude": latitude, "longitude": longitude,
                               "rules": "Parashari; houses counted whole-sign from each chart's own lagna"}),
        "charts": charts,
    }
