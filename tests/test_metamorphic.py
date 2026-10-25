"""Change one fact in a copy of the Zetaris snapshot and the right answer must change with it.

This is the proof that answers are worked out, not stored: the same house, the same code, one edited row.
"""

import os
import shutil
import sqlite3

import pytest

from retrofit import offline, schema
from retrofit.agent.run import Run

F, HID = 1106478076, "osm-way-1106478076"
os.environ["LOG_STDOUT"] = "false"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A writable copy of samples/cache.sqlite that the agent reads instead of the real one."""
    copy = tmp_path / "cache.sqlite"
    shutil.copy(offline.CACHE, copy)
    monkeypatch.setattr(offline, "CACHE", copy)

    def edit(*sql: str, params=()):
        con = sqlite3.connect(copy)
        with con:
            for s in sql:
                con.execute(s, params) if params else con.execute(s)
        con.close()
    return edit


def solar(**kw) -> dict:
    a = Run(offline=True).check(way=F, **kw)["answer"]
    assert schema.check_answer(a) == []
    return a["solar"]


def test_the_unedited_house_is_worth_quotes(cache):
    s = solar()
    assert (s["status"], s["recommendation"]) == ("allowed", "Worth getting quotes")


LISTING = f"INSERT INTO designation VALUES ('{HID}', 'listed-building', '1999999', 'Test listing', 'II', '1974-05-14', NULL, '1', '90')"


def test_a_listing_with_its_outline_needs_consent(cache):
    cache(LISTING, "INSERT INTO listed_outline VALUES ('osm_way_1106478076', '1999999')")
    s = solar()
    assert s["status"] == "needs_consent" and s["recommendation"] == "Ask the council first"
    assert "listed" in s["lines"]["one"].lower() and s["confidence"]["level"] == "high"


def test_a_listing_found_as_a_point_only_is_checked_and_stays_unsure(cache):
    cache(LISTING)
    run = Run(offline=True)
    s = run.check(way=F)["answer"]["solar"]
    assert any(e["type"] == "challenge" and e.get("about") == "listed" for e in run.events)
    assert s["rules_status"] == "needs_consent" and s["status"] == "check_with_council"
    assert "listed_point_only" in s["uncertain"] and s["confidence"]["level"] == "low"


def test_a_solar_article_4_needs_permission(cache):
    cache(f"INSERT INTO designation VALUES ('{HID}', 'article-4-direction-area', 'A4TEST', 'Test roofs', NULL, '2020-01-01', NULL, '2', '90')",
          "INSERT INTO article4_rule VALUES ('London Borough of Camden', 'A4TEST', 'Test roofs', '2020-01-01', NULL, 'true', 'false', 'false', "
          "'Removes permitted development for solar panels on roofs facing a road.', 'https://example.test/a4', '2026-10-25')")
    s = solar()
    assert s["status"] == "needs_permission" and s["recommendation"] == "Ask the council first"


def test_an_article_4_with_unknown_contents_says_check_with_the_council(cache):
    cache(f"INSERT INTO designation VALUES ('{HID}', 'article-4-direction-area', 'A4UNKNOWN', 'Unknown direction', NULL, '2020-01-01', NULL, '3', '90')")
    s = solar()
    assert s["status"] == "check_with_council" and s["status_text"] == "Check with the council"
    assert s["confidence"]["level"] == "low"


def test_a_north_facing_roof_is_not_worth_it(cache):
    cache(f"UPDATE pv_estimate SET facing = 'N', kwh_year = 1500 WHERE house_id = '{HID}'",
          f"UPDATE roof_plane SET facing = 'N', azimuth_deg = '0' WHERE house_id = '{HID}' AND facing = 'S'")
    s = solar()
    assert s["recommendation"] == "Probably not worth it for this house"
    assert "1,500" in s["lines"]["one"] + s["lines"]["get"]


def test_lidar_noise_above_the_limit_marks_the_roof_rough(cache):
    cache(f"UPDATE roof_survey SET noise_pct = '40' WHERE house_id = '{HID}'")
    s = solar()
    assert "lidar_noisy" in s["uncertain"] and s["confidence"]["level"] == "medium"
    assert any("trees or chimneys" in x for x in s["limitations"])


def test_leaving_the_conservation_area_changes_the_reason(cache):
    before = solar()["lines"]["why"]
    cache(f"DELETE FROM designation WHERE house_id = '{HID}' AND dataset = 'conservation-area'")
    after = solar()["lines"]["why"]
    assert "Dartmouth Park" in before and "Dartmouth Park" not in after


def test_electricity_use_changes_the_card(cache):
    low, high = solar(elec_kwh=2500), solar(elec_kwh=4500)
    assert low["numbers"]["value_gbp_year"] != high["numbers"]["value_gbp_year"]
    assert low["lines"]["cost"] != high["lines"]["cost"]
    assert low["usage"]["share_pct"] > high["usage"]["share_pct"]
    assert "2,500" in low["usage"]["text"] and "4,500" in high["usage"]["text"]
