"""Checks on the calculations.

The Swiss Ephemeris itself is the reference for where the planets are, so
these tests do not re-derive astronomy. They check what this package adds:
time handling, the sidereal conversion, nakshatras, houses, the dasha
arithmetic, and every divisional-chart rule against hand-worked cases.
"""

import pytest
import swisseph as swe

from ephemeris_mcp import calc
from ephemeris_mcp.calc import ChartError, varga_sign

S = {name: i for i, name in enumerate(calc.SIGNS)}
J2000 = dict(date="2000-01-01", time="12:00", utc_offset="+00:00")
GREENWICH = dict(latitude=51.4769, longitude=0.0)


def lon(sign, deg):
    return S[sign] * 30 + deg


# ------------------------------------------------------------------ time

def test_offset_is_applied():
    m = calc.moment("2000-01-01", "17:30", utc_offset="+05:30")
    assert m.utc.hour == 12 and m.utc.minute == 0
    assert m.jd_ut == pytest.approx(2451545.0)


def test_zone_names_apply_historical_offsets():
    # India kept war time (+06:30) in 1943; a zone name knows that, and the
    # result says which offset it used so a wrong guess is visible.
    r = calc.planet_positions("1943-06-01", "12:00", timezone="Asia/Kolkata")
    assert r["settings"]["utc_offset_used"] == "+06:30"
    r = calc.planet_positions("1977-01-02", "12:00", timezone="Asia/Kolkata")
    assert r["settings"]["utc_offset_used"] == "+05:30"


@pytest.mark.parametrize("kw", [{}, {"utc_offset": "+05:30", "timezone": "Asia/Kolkata"}])
def test_exactly_one_of_offset_or_zone(kw):
    with pytest.raises(ChartError, match="exactly one"):
        calc.moment("2000-01-01", "12:00", **kw)


@pytest.mark.parametrize("bad", ["5:30", "+25:00", "IST"])
def test_bad_offsets_are_explained(bad):
    with pytest.raises(ChartError, match="utc_offset"):
        calc.moment("2000-01-01", "12:00", utc_offset=bad)


def test_bad_zone_and_date_are_explained():
    with pytest.raises(ChartError, match="not a known zone"):
        calc.moment("2000-01-01", "12:00", timezone="Mars/Olympus")
    with pytest.raises(ChartError, match="YYYY-MM-DD"):
        calc.moment("01/01/2000", "12:00", utc_offset="+00:00")


# ------------------------------------------------------------- positions

def test_lahiri_at_j2000():
    r = calc.planet_positions(**J2000)
    assert "23°51'" in r["settings"]["ayanamsa_value"]


def test_sidereal_is_tropical_minus_ayanamsa():
    sid = calc.planet_positions(**J2000)["planets"]
    trop = calc.planet_positions(**J2000, zodiac="tropical")["planets"]
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    _, aya = swe.get_ayanamsa_ex_ut(2451545.0, swe.FLG_SWIEPH)
    for body in ("Sun", "Moon", "Saturn", "Rahu"):
        assert (trop[body]["longitude"] - aya) % 360 == pytest.approx(sid[body]["longitude"], abs=1e-4)
    # Sun at J2000 is about 280.37° tropical, so about 16°31' Sagittarius sidereal.
    assert sid["Sun"]["sign"] == "Sagittarius" and sid["Sun"]["position"].startswith("16°3")
    assert "nakshatra" not in trop["Sun"], "nakshatras are a sidereal idea"


def test_ketu_is_opposite_rahu_and_true_node_differs():
    p = calc.planet_positions(**J2000)["planets"]
    assert (p["Ketu"]["longitude"] - p["Rahu"]["longitude"]) % 360 == pytest.approx(180)
    t = calc.planet_positions(**J2000, node="true")["planets"]
    assert t["Rahu"]["longitude"] != p["Rahu"]["longitude"]


def test_retrograde_flag_follows_speed():
    p = calc.planet_positions(**J2000)["planets"]
    assert p["Saturn"]["retrograde"] is True      # Saturn was retrograde in Jan 2000
    assert p["Sun"]["retrograde"] is False
    assert all(row["retrograde"] == (row["speed_deg_per_day"] < 0) for row in p.values())


def test_outer_planets_only_on_request():
    assert "Pluto" not in calc.planet_positions(**J2000)["planets"]
    assert "Pluto" in calc.planet_positions(**J2000, include_outer=True)["planets"]


def test_unknown_ayanamsa_lists_choices():
    with pytest.raises(ChartError, match="lahiri"):
        calc.planet_positions(**J2000, ayanamsa="made_up")


@pytest.mark.parametrize("longitude,name,pada,lord", [
    (0.0, "Ashwini", 1, "Ketu"),
    (3.3334, "Ashwini", 2, "Ketu"),
    (13.3334, "Bharani", 1, "Venus"),
    (199.4706, "Swati", 4, "Rahu"),
    (359.999, "Revati", 4, "Mercury"),
])
def test_nakshatra_and_pada(longitude, name, pada, lord):
    n = calc.nakshatra(longitude)
    assert (n["nakshatra"], n["pada"], n["lord"]) == (name, pada, lord)


def test_dms_rounds_without_sixty_seconds():
    assert calc.dms(15.0) == "15°00'00\""
    assert calc.dms(29.99999) == "30°00'00\""
    assert calc.dms(0.5) == "0°30'00\""


# ---------------------------------------------------------------- houses

def test_whole_sign_houses_count_from_the_lagna_sign():
    r = calc.ascendant_and_houses(**J2000, **GREENWICH)
    lagna = S[r["ascendant"]["sign"]]
    assert r["houses"][0]["sign"] == calc.SIGNS[lagna]
    assert r["houses"][3]["sign"] == calc.SIGNS[(lagna + 3) % 12]
    for name, row in r["planets"].items():
        assert row["house"] == (S[row["sign"]] - lagna) % 12 + 1, name
        assert name in r["houses"][row["house"] - 1]["occupants"]


def test_cusp_based_houses_place_planets_between_cusps():
    r = calc.ascendant_and_houses(**J2000, **GREENWICH, house_system="placidus")
    cusps = [h["cusp_longitude"] for h in r["houses"]]
    for row in r["planets"].values():
        i = row["house"] - 1
        start, end = cusps[i], cusps[(i + 1) % 12]
        assert (row["longitude"] - start) % 360 < (end - start) % 360


def test_house_of_handles_the_wrap_past_pisces():
    cusps = [350 + 30 * i for i in range(12)]
    assert calc.house_of(355, 350, cusps, "equal") == 1
    assert calc.house_of(10, 350, cusps, "equal") == 1
    assert calc.house_of(21, 350, cusps, "equal") == 2


def test_polar_placidus_is_explained_not_crashed():
    with pytest.raises(ChartError, match="whole_sign"):
        calc.ascendant_and_houses(**J2000, latitude=75.0, longitude=20.0, house_system="placidus")
    # whole sign works anywhere
    calc.ascendant_and_houses(**J2000, latitude=75.0, longitude=20.0)


def test_place_is_validated():
    with pytest.raises(ChartError, match="latitude"):
        calc.ascendant_and_houses(**J2000, latitude=95, longitude=0)


# ----------------------------------------------------------- vimshottari

def _days(a, b):
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def test_dasha_starts_from_the_moons_nakshatra_lord_with_the_right_balance():
    d = calc.vimshottari_dasha(**J2000, on_date="2026-11-17")
    assert d["moon"]["nakshatra"] == "Swati" and d["balance_at_birth"]["lord"] == "Rahu"
    first = d["mahadashas"][0]
    assert first["lord"] == "Rahu" and "running at birth" in first["note"]
    # Swati is ~96% elapsed, so ~4% of 18 years (~0.72 y, ~263 days) remain.
    remaining = _days("2000-01-01", first["end"])
    assert 255 <= remaining <= 270


def test_dasha_order_and_lengths():
    d = calc.vimshottari_dasha(**J2000, levels=2)
    lords = [m["lord"] for m in d["mahadashas"]]
    assert lords[:9] == ["Rahu", "Jupiter", "Saturn", "Mercury", "Ketu", "Venus", "Sun", "Moon", "Mars"]
    assert sum(m["years"] for m in d["mahadashas"][:9]) == 120
    for m in d["mahadashas"][:9]:
        assert _days(m["start"], m["end"]) == pytest.approx(m["years"] * 365.25, abs=1)
        subs = m["antardashas"]
        assert subs[0]["lord"] == m["lord"], "each mahadasha opens with its own antardasha"
        assert sum(s["years"] for s in subs) == pytest.approx(m["years"], abs=1e-3)
        assert subs[0]["start"] == m["start"] and subs[-1]["end"] == m["end"]


def test_current_periods_contain_the_date_and_nest():
    d = calc.vimshottari_dasha(**J2000, levels=3, on_date="2026-11-17")
    c = d["current"]
    for level in ("mahadasha", "antardasha", "pratyantardasha"):
        assert c[level]["start"] <= "2026-11-17" < c[level]["end"], level
    assert c["mahadasha"]["start"] <= c["antardasha"]["start"]
    assert c["antardasha"]["end"] <= c["mahadasha"]["end"]
    assert c["pratyantardashas"][0]["lord"] == c["antardasha"]["lord"]
    assert sum(p["years"] for p in c["pratyantardashas"]) == pytest.approx(c["antardasha"]["years"], abs=1e-3)


def test_year_length_changes_the_dates():
    a = calc.vimshottari_dasha(**J2000, levels=1)
    b = calc.vimshottari_dasha(**J2000, levels=1, year_days=360)
    assert a["mahadashas"][3]["start"] != b["mahadashas"][3]["start"]
    with pytest.raises(ChartError, match="year_days"):
        calc.vimshottari_dasha(**J2000, year_days=400)


def test_levels_one_has_no_antardashas():
    d = calc.vimshottari_dasha(**J2000, levels=1)
    assert "antardashas" not in d["mahadashas"][0]


# ------------------------------------------------------ divisional charts

@pytest.mark.parametrize("n,sign,deg,expected", [
    # D2 Hora: odd signs Sun (Leo) then Moon (Cancer); even signs the reverse
    (2, "Aries", 10, "Leo"), (2, "Aries", 20, "Cancer"),
    (2, "Taurus", 10, "Cancer"), (2, "Taurus", 20, "Leo"),
    # D3 Drekkana: same, 5th, 9th
    (3, "Aries", 5, "Aries"), (3, "Aries", 15, "Leo"), (3, "Aries", 25, "Sagittarius"),
    (3, "Cancer", 25, "Pisces"),
    # D4: same, 4th, 7th, 10th
    (4, "Taurus", 8, "Leo"), (4, "Taurus", 29, "Aquarius"),
    # D7: odd from itself, even from the 7th
    (7, "Aries", 29, "Libra"), (7, "Taurus", 1, "Scorpio"),
    # D9: fire from Aries, earth Capricorn, air Libra, water Cancer
    (9, "Aries", 1, "Aries"), (9, "Taurus", 1, "Capricorn"), (9, "Gemini", 1, "Libra"),
    (9, "Cancer", 1, "Cancer"), (9, "Cancer", 29, "Pisces"), (9, "Sagittarius", 16.5, "Leo"),
    # D10: odd from itself, even from the 9th
    (10, "Aries", 1, "Aries"), (10, "Taurus", 1, "Capricorn"), (10, "Taurus", 29, "Libra"),
    # D12: from itself
    (12, "Leo", 29, "Cancer"),
    # D16: movable Aries, fixed Leo, dual Sagittarius
    (16, "Cancer", 1, "Aries"), (16, "Taurus", 1, "Leo"), (16, "Gemini", 1, "Sagittarius"),
    # D20: movable Aries, fixed Sagittarius, dual Leo
    (20, "Libra", 1, "Aries"), (20, "Taurus", 1, "Sagittarius"), (20, "Gemini", 1, "Leo"),
    # D24: odd from Leo, even from Cancer
    (24, "Aries", 1, "Leo"), (24, "Taurus", 1, "Cancer"),
    # D27: fire Aries, earth Cancer, air Libra, water Capricorn
    (27, "Leo", 1, "Aries"), (27, "Taurus", 1, "Cancer"), (27, "Aquarius", 0.5, "Libra"),
    (27, "Cancer", 1, "Capricorn"),
    # D30: odd 5 Mars, 5 Saturn, 8 Jupiter, 7 Mercury, 5 Venus; even reversed
    (30, "Aries", 3, "Aries"), (30, "Aries", 7, "Aquarius"), (30, "Aries", 15, "Sagittarius"),
    (30, "Aries", 20, "Gemini"), (30, "Aries", 27, "Libra"),
    (30, "Taurus", 3, "Taurus"), (30, "Taurus", 8, "Virgo"), (30, "Taurus", 15, "Pisces"),
    (30, "Taurus", 22, "Capricorn"), (30, "Taurus", 28, "Scorpio"),
    # D40: odd from Aries, even from Libra
    (40, "Gemini", 0.1, "Aries"), (40, "Taurus", 0.1, "Libra"),
    # D45: movable Aries, fixed Leo, dual Sagittarius
    (45, "Capricorn", 0.1, "Aries"), (45, "Leo", 0.1, "Leo"), (45, "Pisces", 0.1, "Sagittarius"),
    # D60: counted from the sign itself
    (60, "Aries", 0.6, "Taurus"), (60, "Taurus", 29.9, "Aries"),
])
def test_varga_rules(n, sign, deg, expected):
    assert calc.SIGNS[varga_sign(lon(sign, deg), n)] == expected


@pytest.mark.parametrize("n", calc.SUPPORTED_DIVISIONS)
def test_every_division_is_defined_across_the_whole_zodiac(n):
    # Each sign splits into n parts (D2 and D30 into their own fixed parts),
    # and the last instant before a sign boundary still belongs to it.
    for s in range(12):
        seen = [varga_sign(s * 30 + (k + 0.5) * 30 / n, n) for k in range(n)]
        assert all(0 <= x < 12 for x in seen)
        varga_sign(s * 30 + 29.9999999, n)


def test_divisional_charts_whole_result():
    r = calc.divisional_charts(**J2000, **GREENWICH, divisions=[1, 9, 60])
    d1, d9 = r["charts"]["D1"], r["charts"]["D9"]
    assert d9["name"] == "Navamsha"
    assert d9["placements"]["Sun"]["sign"] == "Leo"
    # D1 must agree with the plain positions
    pos = calc.planet_positions(**J2000)["planets"]
    for body in ("Sun", "Moon", "Mars", "Rahu"):
        assert d1["placements"][body]["sign"] == pos[body]["sign"]
    # vargottama only where navamsha and rashi signs match
    for body, row in d9["placements"].items():
        rashi = d1["placements"][body]["sign"]
        assert row.get("vargottama", False) == (row["sign"] == rashi)
    # houses counted from each chart's own lagna
    lag = S[d9["lagna"]]
    for row in d9["placements"].values():
        assert row["house"] == (S[row["sign"]] - lag) % 12 + 1


def test_unsupported_division_is_explained():
    with pytest.raises(ChartError, match="D5 is not supported"):
        calc.divisional_charts(**J2000, **GREENWICH, divisions=[5])
