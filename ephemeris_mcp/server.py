"""The MCP server: exposes the chart calculations as tools.

Runs over stdio, which is how the coding assistant (and most MCP clients)
start a local server. Every tool takes the birth moment the same way:
date, time, and exactly one of utc_offset or timezone.
"""

from __future__ import annotations

import json
import threading
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import calc
from .calc import ChartError

__version__ = "0.1.0"

server = MCPServer(
    name="ephemeris",
    version=__version__,
    instructions=(
        "Astrological chart calculations using the Swiss Ephemeris. Defaults are Vedic: "
        "sidereal zodiac, Lahiri ayanamsa, mean nodes, whole-sign houses, Parashari divisional "
        "charts, Vimshottari with a 365.25-day year. Give birth time as local clock time plus "
        "either utc_offset or an IANA timezone; check settings.utc_offset_used in every result, "
        "because zone names apply historical offsets (e.g. Indian war time 1942-45). Latitude "
        "and longitude are decimal degrees, north and east positive; look them up if the user "
        "gives only a place name. These tools calculate; they do not interpret."
    ),
)

# Shared parameter shapes, so every tool describes them identically.
DateArg = Annotated[str, Field(description="Local birth date, YYYY-MM-DD")]
TimeArg = Annotated[str, Field(description="Local clock time, 24-hour HH:MM or HH:MM:SS")]
OffsetArg = Annotated[str | None, Field(description='UTC offset in force at birth, e.g. "+05:30". Give this OR timezone.')]
ZoneArg = Annotated[str | None, Field(description='IANA zone name, e.g. "Asia/Kolkata"; historical rules are applied. Give this OR utc_offset.')]
LatArg = Annotated[float, Field(description="Latitude in decimal degrees, north positive", ge=-90, le=90)]
LonArg = Annotated[float, Field(description="Longitude in decimal degrees, east positive", ge=-180, le=180)]
AyanamsaArg = Annotated[
    Literal["lahiri", "lahiri_icrc", "raman", "krishnamurti", "true_chitra", "yukteshwar", "fagan_bradley"],
    Field(description="Ayanamsa for the sidereal zodiac"),
]
NodeArg = Annotated[Literal["mean", "true"], Field(description="Mean or true lunar node for Rahu/Ketu")]
ZodiacArg = Annotated[Literal["sidereal", "tropical"], Field(description="Sidereal (Vedic) or tropical (Western)")]

READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}


# The Swiss Ephemeris keeps settings such as the ayanamsa in global state,
# and the server runs tools on worker threads, so calls take turns.
_SWE_LOCK = threading.Lock()


def _run(fn, **kwargs) -> str:
    try:
        with _SWE_LOCK:
            result = fn(**kwargs)
        # Compact JSON: half the size of pretty-printed, which matters
        # because clients cap tool results (the coding assistant at 20,000
        # characters) and every character is paid for in tokens.
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    except ChartError as err:
        # A ToolError reaches the model as a readable error it can correct
        # (a missing offset, a bad date), rather than a generic crash.
        raise ToolError(str(err)) from None


@server.tool(annotations=READ_ONLY)
def planet_positions(
    date: DateArg,
    time: TimeArg,
    utc_offset: OffsetArg = None,
    timezone: ZoneArg = None,
    zodiac: ZodiacArg = "sidereal",
    ayanamsa: AyanamsaArg = "lahiri",
    node: NodeArg = "mean",
    include_outer: Annotated[bool, Field(description="Also give Uranus, Neptune and Pluto")] = False,
) -> str:
    """Longitude, sign, degree, nakshatra and pada, speed and retrograde status for the
    Sun through Saturn plus Rahu and Ketu, at a birth moment. No place needed."""
    return _run(calc.planet_positions, date=date, time=time, utc_offset=utc_offset, timezone=timezone,
                zodiac=zodiac, ayanamsa=ayanamsa, node=node, include_outer=include_outer)


@server.tool(annotations=READ_ONLY)
def ascendant_and_houses(
    date: DateArg,
    time: TimeArg,
    latitude: LatArg,
    longitude: LonArg,
    utc_offset: OffsetArg = None,
    timezone: ZoneArg = None,
    house_system: Annotated[
        Literal["whole_sign", "sripati", "placidus", "koch", "equal", "porphyry"],
        Field(description="House system; whole_sign is the Vedic default, sripati gives bhava cusps"),
    ] = "whole_sign",
    zodiac: ZodiacArg = "sidereal",
    ayanamsa: AyanamsaArg = "lahiri",
    node: NodeArg = "mean",
    include_outer: Annotated[bool, Field(description="Also give Uranus, Neptune and Pluto")] = False,
) -> str:
    """The ascendant (lagna), midheaven, twelve house cusps with their occupants, and
    every planet's position with its house number."""
    return _run(calc.ascendant_and_houses, date=date, time=time, latitude=latitude, longitude=longitude,
                utc_offset=utc_offset, timezone=timezone, house_system=house_system, zodiac=zodiac,
                ayanamsa=ayanamsa, node=node, include_outer=include_outer)


@server.tool(annotations=READ_ONLY)
def vimshottari_dasha(
    date: DateArg,
    time: TimeArg,
    utc_offset: OffsetArg = None,
    timezone: ZoneArg = None,
    ayanamsa: AyanamsaArg = "lahiri",
    levels: Annotated[
        Literal[1, 2, 3],
        Field(description="1 = mahadashas; 2 = with antardashas; 3 = also every pratyantardasha of the current antardasha"),
    ] = 2,
    on_date: Annotated[str | None, Field(description="YYYY-MM-DD for 'current'; default today")] = None,
    year_days: Annotated[float, Field(description="Days per dasha year; 365.25 usual, 360 savana", ge=360, le=366)] = 365.25,
) -> str:
    """Vimshottari dasha periods from the Moon's nakshatra: balance at birth, the
    mahadasha/antardasha/pratyantardasha running on a given date, and the full timeline."""
    return _run(calc.vimshottari_dasha, date=date, time=time, utc_offset=utc_offset, timezone=timezone,
                ayanamsa=ayanamsa, levels=levels, on_date=on_date, year_days=year_days)


@server.tool(annotations=READ_ONLY)
def divisional_charts(
    date: DateArg,
    time: TimeArg,
    latitude: LatArg,
    longitude: LonArg,
    utc_offset: OffsetArg = None,
    timezone: ZoneArg = None,
    divisions: Annotated[
        list[int],
        Field(description="Which vargas, e.g. [9] or [2, 3, 9, 10, 60]. Supported: 1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60"),
    ] = [9],
    ayanamsa: AyanamsaArg = "lahiri",
    node: NodeArg = "mean",
) -> str:
    """Parashari divisional charts (vargas): the lagna and each planet's sign and house in
    each requested division. Navamsha placements in the same sign as the rashi are marked vargottama."""
    return _run(calc.divisional_charts, date=date, time=time, latitude=latitude, longitude=longitude,
                utc_offset=utc_offset, timezone=timezone, divisions=divisions, ayanamsa=ayanamsa, node=node)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
