# ephemeris-mcp

Astrological chart calculations from the Swiss Ephemeris, exposed as an
[MCP](https://modelcontextprotocol.io) server. Add it to an AI assistant that
speaks MCP and the assistant can calculate a chart itself instead of
guessing at planetary positions.

It **calculates**; it does not interpret. Birth details go in, positions and
periods come out. Nothing is stored and nothing is sent anywhere.

## The four tools

| Tool | Gives you |
|---|---|
| `planet_positions` | Sun to Saturn, Rahu and Ketu (optionally Uranus, Neptune, Pluto): longitude, sign, degree, nakshatra and pada, speed, retrograde |
| `ascendant_and_houses` | Lagna, midheaven, the twelve houses with their occupants, each planet's house |
| `vimshottari_dasha` | Balance at birth, the mahadasha / antardasha / pratyantardasha running on a date, and the full timeline |
| `divisional_charts` | Any of D1, D2, D3, D4, D7, D9, D10, D12, D16, D20, D24, D27, D30, D40, D45, D60: the lagna and every planet's sign and house; vargottama marked in D9 |

Every result starts with a `settings` block that states exactly what was
used: the UTC offset, ayanamsa and its value, house system, node type and
ephemeris. When two programs disagree about a chart, the cause is almost
always one of these, so they are never left implicit.

## Defaults

Vedic, as most Jyotish software ships them. Each can be changed per call.

| Setting | Default | Alternatives |
|---|---|---|
| Zodiac | sidereal | tropical |
| Ayanamsa | Lahiri | lahiri_icrc, raman, krishnamurti, true_chitra, yukteshwar, fagan_bradley |
| Nodes | mean | true |
| Houses | whole sign | sripati, placidus, koch, equal, porphyry |
| Dasha year | 365.25 days | anything from 360 (savana) to 366 |
| Divisional charts | Parashari rules | — |

## Install

Needs Python 3.10 or newer. On Rocky Linux / RHEL 9, where the system
Python is 3.9, install a newer one first: `sudo dnf install python3.12`.

```bash
git clone https://github.com/plasticknight/ephemeris-mcp.git
cd ephemeris-mcp
python3.12 -m venv .venv
.venv/bin/pip install .
.venv/bin/pip install pytest && .venv/bin/pytest -q     # optional: ~100 checks, all offline
```

`pyswisseph` ships pre-built for common platforms. Where it doesn't, pip
compiles it, which needs a C compiler (`sudo dnf install gcc python3.12-devel`).

## Connect it

### Coding Assistant

In `mcp-servers.json`, inside `"servers"`:

```json
"ephemeris": {
  "command": "/full/path/to/ephemeris-mcp/.venv/bin/ephemeris-mcp",
  "autoApprove": ["planet_positions", "ascendant_and_houses", "vimshottari_dasha", "divisional_charts"]
}
```

Then click the MCP status dot to reload, or restart the app. The tools are
read-only, which is why auto-approving them is reasonable.

### Any other MCP client

It is a standard stdio server. Point the client at
`.venv/bin/ephemeris-mcp` (or `python -m ephemeris_mcp` with that venv's
Python).

## Giving it a birth moment

Every tool takes:

- `date` — local date, `YYYY-MM-DD`
- `time` — local clock time, `HH:MM` or `HH:MM:SS`, 24-hour
- **exactly one** of
  - `utc_offset` — the offset in force, e.g. `"+05:30"`, or
  - `timezone` — a zone name, e.g. `"Asia/Kolkata"`

and the house and divisional-chart tools also take `latitude` and
`longitude` in decimal degrees (north and east positive).

**Zone names apply history.** `Asia/Kolkata` gives +06:30 for 1942–45 (war
time) and older local-mean-time offsets before 1941. That is often what you
want and sometimes not what the birth record meant. The offset actually
used is always in `settings.utc_offset_used`; if in doubt, give
`utc_offset` explicitly.

There is no place-name lookup, because that would need the network. The
assistant can look the coordinates up and pass them in.

## Accuracy

With no setup it uses the Swiss Ephemeris's built-in Moshier model,
accurate to about one arc-second for the planets between roughly 3000 BC
and AD 3000. That is far finer than any chart needs.

For the full-precision data files, download them from the
[Swiss Ephemeris](https://www.astro.com/swisseph/) site and point the server
at them:

```json
"env": { "SE_EPHE_PATH": "/path/to/ephe" }
```

`settings.ephemeris` says which one a result came from.

### How it was checked

- Each divisional-chart rule against hand-worked cases, and all fifteen
  divisions against [PyJHora](https://github.com/naturalstupid/PyJHora) across
  7,200 longitudes: identical.
- Vimshottari against PyJHora for five charts (405 antardashas): same
  lords, dates within a day. PyJHora defaults to a solar-arc year rather than
  a fixed day count, so compare with its mean-year setting.
- The sidereal conversion, nakshatra boundaries, node opposition, house
  placement and time handling, in `tests/`.

## Licence

AGPL-3.0-or-later, because the Swiss Ephemeris is distributed under the
AGPL. If you build this into something you offer to others, the AGPL's
source-sharing terms apply to that too. A commercial Swiss Ephemeris
licence from Astrodienst is the alternative.

Swiss Ephemeris © Astrodienst AG.
