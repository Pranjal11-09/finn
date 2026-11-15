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
