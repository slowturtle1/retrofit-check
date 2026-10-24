"""The code half of the critic catches planted mistakes before any model sees them."""

import json
from datetime import date
from pathlib import Path

from retrofit import rules
from retrofit.agent import explain

HERE = Path(__file__).parent
D = json.loads((HERE / "house_d_facts.json").read_text())
R = rules.evaluate(D, heating="gas", today=date(2026, 10, 24))
V = {v["measure"]: v for v in R["verdicts"]}


def draft(m):
    return explain.template(R, V[m])


def test_the_drafts_pass_their_own_checks():
    for m in V:
        assert explain.check_rewrite(R, V[m], draft(m), {"one": draft(m)["one"], "why": draft(m)["why"]}) == []


def test_a_planted_number_is_caught():
    d = draft("solar")
    bad = {"one": d["one"].replace("3,182", "4,500"), "why": d["why"]}
    assert any("4500" in p for p in explain.check_rewrite(R, V["solar"], d, bad))


def test_softening_a_refusal_is_caught():
    d = draft("wall_insulation")
    bad = {"one": "You can clad your walls.", "why": d["why"]}
    assert any("permission" in p for p in explain.check_rewrite(R, V["wall_insulation"], d, bad))


def test_turning_an_allowed_answer_into_a_refusal_is_caught():
    d = draft("solar")
    bad = {"one": "Panels need planning permission here.", "why": d["why"]}
    assert any("contradicts" in p for p in explain.check_rewrite(R, V["solar"], d, bad))


def test_dropping_the_conservation_area_name_is_caught():
    d = draft("wall_insulation")
    bad = {"one": "Cladding the outside walls needs planning permission.", "why": "Covering outside walls needs planning permission."}
    assert any("Dartmouth Park" in p for p in explain.check_rewrite(R, V["wall_insulation"], d, bad))
