"""The server, spoken to the way a real MCP client speaks to it: started as
a separate process over stdio."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
BIRTH = {"date": "2000-01-01", "time": "17:30", "utc_offset": "+05:30"}
PLACE = {"latitude": 17.385, "longitude": 78.4867}


def _session(fn):
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ephemeris_mcp"], cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await fn(s)
    return asyncio.run(go())


def _json(result):
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


def test_lists_four_read_only_tools():
    async def f(s):
        return (await s.list_tools()).tools
    tools = _session(f)
    assert {t.name for t in tools} == {"planet_positions", "ascendant_and_houses", "vimshottari_dasha", "divisional_charts"}
    for t in tools:
        assert t.annotations and t.annotations.read_only_hint, t.name
        assert "date" in t.input_schema["required"] and "time" in t.input_schema["required"]


def test_every_tool_answers():
    async def f(s):
        return [
            await s.call_tool("planet_positions", BIRTH),
            await s.call_tool("ascendant_and_houses", {**BIRTH, **PLACE}),
            await s.call_tool("vimshottari_dasha", {**BIRTH, "on_date": "2026-11-17"}),
            await s.call_tool("divisional_charts", {**BIRTH, **PLACE, "divisions": [9, 10]}),
        ]
    pos, houses, dasha, vargas = (_json(r) for r in _session(f))
    assert pos["planets"]["Sun"]["sign"] == "Sagittarius"
    assert pos["settings"]["utc"] == "2000-01-01T12:00:00Z"
    assert len(houses["houses"]) == 12 and houses["settings"]["house_system"] == "whole_sign"
    assert dasha["current"]["mahadasha"]["lord"] == "Saturn"
    assert set(vargas["charts"]) == {"D9", "D10"}


def test_mistakes_come_back_as_readable_errors():
    async def f(s):
        return [
            await s.call_tool("planet_positions", {"date": "2000-01-01", "time": "12:00"}),
            await s.call_tool("divisional_charts", {**BIRTH, **PLACE, "divisions": [5]}),
        ]
    missing, bad_div = _session(f)
    assert missing.is_error and "utc_offset" in missing.content[0].text
    assert bad_div.is_error and "D5 is not supported" in bad_div.content[0].text


def test_largest_results_fit_a_20000_character_client_cap():
    # The coding assistant truncates tool results at 20,000 characters; a
    # cut-off JSON timeline would be worse than useless.
    from ephemeris_mcp import calc, server
    worst = [
        server._run(calc.divisional_charts, **BIRTH, **PLACE, divisions=calc.SUPPORTED_DIVISIONS),
        # A Moon at the very start of a nakshatra gives the longest timeline.
        server._run(calc.vimshottari_dasha, date="2000-01-07", time="06:00", utc_offset="+00:00", levels=3),
        server._run(calc.ascendant_and_houses, **BIRTH, **PLACE, include_outer=True),
    ]
    for text in worst:
        assert len(text) < 15000, len(text)
        json.loads(text)
