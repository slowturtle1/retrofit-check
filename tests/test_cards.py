"""The solar card: one fixture for every answer the agent can give, and the wording rules on every card.

Fixtures are house F (Dartmouth Park) with one edit to a copy of the Zetaris snapshot each, plus the
real sample houses. The wording rules run over all of them.
"""

import os
import re
import shutil
import sqlite3

import pytest

from retrofit import offline, schema
from retrofit.agent.run import Run
from retrofit.offline import houses
from retrofit.rules import COMPASS

os.environ["LOG_STDOUT"] = "false"
F, HID = 1106478076, "osm-way-1106478076"
WORTH, NOT_WORTH, COUNCIL = "Worth getting quotes", "Probably not worth it for this house", "Ask the council first"
LISTING = f"INSERT INTO designation VALUES ('{HID}', 'listed-building', '1999999', 'Test listing', 'II', '1974-05-14', NULL, '1', '90')"

# name: (edits to the snapshot, shown status, recommendation, confidence)
FIXTURES = {
    "allowed, worth quotes": ([], "allowed", WORTH, "high"),
    "allowed, flat roof in a conservation area": ([f"UPDATE roof_survey SET flat_pct = '80' WHERE house_id = '{HID}'"], "allowed", WORTH, "high"),
    "allowed, rough roof reading": ([f"UPDATE roof_survey SET noise_pct = '40' WHERE house_id = '{HID}'"], "allowed", WORTH, "medium"),
    "allowed, no sunny roof": ([f"DELETE FROM pv_estimate WHERE house_id = '{HID}'"], "allowed", NOT_WORTH, "medium"),
    "allowed, too small": ([f"UPDATE pv_estimate SET kwp = '1.0', kwh_year = '1000' WHERE house_id = '{HID}'"], "allowed", NOT_WORTH, "high"),
    "allowed, little sun per kWp": ([f"UPDATE pv_estimate SET facing = 'N', kwh_year = '1500' WHERE house_id = '{HID}'"], "allowed", NOT_WORTH, "high"),
    "needs listed building consent": ([LISTING, "INSERT INTO listed_outline VALUES ('osm_way_1106478076', '1999999')"], "needs_consent", COUNCIL, "high"),
    "needs planning permission (solar Article 4)": ([
        f"INSERT INTO designation VALUES ('{HID}', 'article-4-direction-area', 'A4TEST', 'Test roofs', NULL, '2020-01-01', NULL, '2', '90')",
        "INSERT INTO article4_rule VALUES ('London Borough of Camden', 'A4TEST', 'Test roofs', '2020-01-01', NULL, 'true', 'false', 'false', "
        "'Removes permitted development for solar panels on roofs.', 'https://example.test/a4', '2026-10-25')"], "needs_permission", COUNCIL, "high"),
    "check with the council (Article 4 contents unknown)": ([
        f"INSERT INTO designation VALUES ('{HID}', 'article-4-direction-area', 'A4UNKNOWN', 'Unknown direction', NULL, '2020-01-01', NULL, '3', '90')"],
        "check_with_council", COUNCIL, "low"),
    "check with the council (listing found as a point only)": ([LISTING], "check_with_council", COUNCIL, "low"),
}


def _answer(way=None, lat=None, lon=None) -> dict:
    rec = Run(offline=True).check(way=way, lat=lat, lon=lon)
    return {**rec["answer"], "_result": rec["result"]}


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory) -> dict:
    out = {}
    for name, (edits, *_ ) in FIXTURES.items():
        copy = tmp_path_factory.mktemp("cache") / "cache.sqlite"
        shutil.copy(offline.CACHE, copy)
        con = sqlite3.connect(copy)
        with con:
            for sql in edits:
                con.execute(sql)
        con.close()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(offline, "CACHE", copy)
            out[name] = _answer(way=F)
    return out


@pytest.fixture(scope="module")
def samples() -> dict:
    out = {}
    for h in houses():
        way = int(h["house_id"].rsplit("-", 1)[1]) if h["house_id"].startswith("osm-way-") else None
        out[h["label"]] = _answer(way=way, lat=None if way else h["lat"], lon=None if way else h["lon"])
    return out


@pytest.fixture(scope="module")
def every(fixtures, samples) -> dict:
    return {**{f"F, {k}": v for k, v in fixtures.items()}, **samples}


def test_every_solar_answer_has_a_fixture(fixtures):
    got = {}
    for name, (_, status, rec, level) in FIXTURES.items():
        s = fixtures[name]["solar"]
        assert schema.check_answer(fixtures[name]) == [], name
        got[name] = (s["status"], s["recommendation"], s["confidence"]["level"])
        assert got[name] == (status, rec, level), (name, got[name])
    combos = {(st, rec) for st, rec, _ in got.values()}
    assert combos == {("allowed", WORTH), ("allowed", NOT_WORTH), ("needs_consent", COUNCIL), ("needs_permission", COUNCIL), ("check_with_council", COUNCIL)}


def test_unsure_never_says_allowed(every):
    for name, a in every.items():
        s = a["solar"]
        if s["confidence"]["level"] == "low" or s["status"] == "check_with_council":
            assert s["status"] == "check_with_council" and s["status_text"] == "Check with the council", name
            assert not re.search(r"\ballowed\b", s["status_text"] + " " + s["lines"]["one"], re.I), name
            assert s["recommendation"] == COUNCIL, name


def test_money_is_marked_as_an_estimate(every):
    for name, a in every.items():
        s = a["solar"]
        if s["numbers"].get("cost_gbp"):
            assert re.search(r"\babout\b", s["lines"]["cost"]), name
            assert any(re.search(r"estimate|MCS tables|may differ", x, re.I) for x in s["limitations"]), name


def test_not_advice_line(every):
    for name, a in every.items():
        assert any(x == "Not legal or financial advice." for x in a["solar"]["limitations"]), name


def test_allowed_answers_point_to_quotes_and_a_certificate(every):
    for name, a in every.items():
        s = a["solar"]
        if s["status"] == "allowed":
            assert "lawful development certificate" in s["next_step"].lower(), name
            assert ("quotes" in s["next_step"].lower()) == (s["recommendation"] == WORTH), name


def test_lines_start_with_a_capital_and_have_no_nested_brackets(every):
    for name, a in every.items():
        for k, line in a["solar"]["lines"].items():
            assert line and line[0].isupper(), (name, k, line[:40])
            assert not re.search(r"\([^)]*\(|\[[^\]]*\[", line), (name, k, line[:80])
            assert "—" not in line, (name, k)


def _same_roof(a: dict, b: dict) -> bool:
    keep = ("kwp", "kwh_year", "facing")
    na, nb = a["solar"]["numbers"], b["solar"]["numbers"]
    return bool(na.get("kwp")) and all(na.get(k) == nb.get(k) for k in keep)


@pytest.mark.pending("A2")
def test_no_line_identical_on_two_houses_with_different_facts(samples):
    """Two houses may share a line only when it is built from numbers they share (same roof size and yield)."""
    seen: dict = {}
    clashes = []
    for name, a in samples.items():
        facts = tuple(f["value"] for f in a["house_facts"])
        for k, line in a["solar"]["lines"].items():
            other = seen.get((k, line))
            if other and other[1] != facts and not _same_roof(other[2], a):
                clashes.append(f"{k} line on {other[0]} and {name}: {line[:80]}")
            seen[(k, line)] = (name, facts, a)
    assert not clashes, clashes


def _tokens(a: dict) -> set[str]:
    """Facts of this house as they can appear in a sentence: numbers, names, the roof direction, the council."""
    out = set()
    for f in a["house_facts"]:
        v = f["value"] or ""
        out |= set(re.findall(r"\d[\d,.]*", v))
        out |= {m.strip() for m in re.findall(r"(?:^|, )([A-Z][\w' ]+?)(?: \(\d{4}\)|$|,)", v) if m.strip() not in ("None", "Not listed")}
        out |= set(re.findall(r" to ([A-Z][\w' ]+)", v))
        out |= set(re.findall(r"Grade I+\*?", v))
    n = a["solar"]["numbers"]
    for k in ("kwp", "kwh_year"):
        if n.get(k):
            out.add(f"{n[k]:,}" if isinstance(n[k], int) else str(n[k]))
    for x in (n.get("cost_gbp") or []) + (n.get("value_gbp_year") or []):
        out.add(f"£{x:,}")
    if n.get("facing"):
        out.add(COMPASS[["N", "NE", "E", "SE", "S", "SW", "W", "NW"].index(n["facing"])])
    if a["_result"].get("council"):
        out.add(str(a["_result"]["council"]).replace("London Borough of ", "").replace("City of ", "").split(" Council")[0])
    return {t for t in out if len(t) > 1}


def test_every_line_holds_a_fact_of_its_house(samples):
    for name, a in samples.items():
        toks = _tokens(a)
        for k, line in a["solar"]["lines"].items():
            assert any(t in line for t in toks), f"{name}, {k}: no fact of this house in '{line[:100]}' (facts: {sorted(toks)[:12]})"
