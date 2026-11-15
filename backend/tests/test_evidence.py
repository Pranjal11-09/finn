from app.pull.evidence import validate_synthesis, validate_answer
from app.push.enrich import _ebitda, _card_from_lines, _verdict

def test_missing_inputs_are_not_zero():
    assert _ebitda({"pbt": [100, 90, 80]}) == [None, None, None]


def test_comma_numbers_and_nil_exceptional():
    from app.push.enrich import _clean_lines
    x = _clean_lines({"revenue": ["9,525.15", "9,462.12", "9,121.25"], "other_income": ["186.15", "165.21", "340.84"],
                      "finance_costs": ["387.26", "371.36", "132.63"], "depreciation": ["347.33", "402.53", "198.98"],
                      "exceptional": [None, None, None], "pbt": ["647.31", "772.21", "1,481.19"], "pat": ["(1.5)", "2", "-"]})
    assert x["revenue"][0] == 9525.15 and x["pat"] == [-1.5, 2.0, None]
    assert round(_ebitda(x)[0], 2) == round(647.31 + 387.26 + 347.33 - 186.15, 2)

def test_no_causal_claim_from_pat_growth():
    x = {"revenue": [100]*3, "ebitda": [30]*3, "pat": [20,10,10], "pbt": [20,10,10]}
    assert "operating leverage" not in _verdict(_card_from_lines(x, 1, "test"))

def test_model_verdicts_are_discarded_and_bad_cites_dropped():
    out = validate_synthesis({"promise_vs_delivery": [{"cite": "S1 p.1", "verdict": "delivered"}],
                              "scorecard": {"credibility": "high"},
                              "narrative_vs_numbers": [{"claim": "a", "cite": "S1 p.1"}, {"claim": "b", "cite": "S1 p.9"}]},
                             {"S1": ["text"]})
    assert "promise_vs_delivery" not in out and "scorecard" not in out
    assert [r["claim"] for r in out["narrative_vs_numbers"]] == ["a"]


def test_unknown_qa_page_rejected():
    out = validate_answer({"answer":"Revenue grew [S1 p.99]"}, [{"sid":"S1","page":1}])
    assert "could not validate" in out["answer"]


def test_synthesis_drops_uncited_and_invented_sources():
    out = validate_synthesis({"bull": ["No source", "Growth [S1 p.9]", "Cash [N:annual]", "Demand [S1 p.1]"],
                              "bear": ["Bad [N:invented]", "Mixed [S1 p.1] [S2 p.1]"]}, {"S1": ["text"]})
    assert out["bull"] == ["Cash [N:annual]", "Demand [S1 p.1]"]
    assert out["bear"] == []


def test_answer_returns_only_used_sources():
    hits = [{"sid": "S1", "page": 1, "title": "Call"}, {"sid": "S2", "page": 3, "title": "Report"}]
    out = validate_answer({"answer": "Revenue grew [S1 p.1]"}, hits)
    assert out["cites"] == hits[:1]
    assert validate_answer({"answer": "Invented [S3 p.1]"}, hits)["cites"] == []


def test_results_reject_bad_unit_page_and_hallucinated_number():
    from copy import deepcopy
    import pytest
    from app.push.enrich import validate_extraction
    valid = {"unit": "lakh", "basis": "consolidated", "page": 1,
             "periods": {"current": "Sep 2026", "previous": "Jun 2026", "year_ago": "Sep 2025"},
             "revenue": ["9,525.15", "8,000", "7,000"]}
    pages = ["Revenue from operations 9,525.15 8,000 7,000"]
    assert validate_extraction(deepcopy(valid), pages, [0])["revenue"][0] == 9525.15
    for patch in ({"unit": "rupees"}, {"page": 2}, {"page": True}, {"basis": "unknown"},
                  {"periods": {}}, {"revenue": [999999, 8000, 7000]}):
        with pytest.raises(ValueError):
            validate_extraction({**deepcopy(valid), **patch}, pages, [0])


def test_nonfinite_numbers_are_missing():
    from app.push.enrich import _n
    assert _n("nan") is None and _n(float("inf")) is None


def test_guidance_rejects_invented_quotes_and_wrong_pages():
    from app.pull.evidence import validate_guidance
    rows = [{"quote": "We expect 12–14% growth", "page": 1},
            {"quote": "We expect 99% growth", "page": 1},
            {"quote": "We expect 12–14% growth", "page": 2}]
    out = validate_guidance({"guidance": rows}, ["CFO: We expect 12-14% growth."])
    assert out["guidance"] == rows[:1]
