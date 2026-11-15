"""Run: cd backend && FINN_FIXTURES=1 FINN_DB=/tmp/finn_test.db python -m pytest -q"""
import asyncio
import json
import os

os.environ.setdefault("FINN_FIXTURES", "1")
os.environ.setdefault("FINN_DB", "/tmp/finn_test.db")
os.environ["LLM_PROVIDER"] = "off"
if os.path.exists(os.environ["FINN_DB"]):
    os.remove(os.environ["FINN_DB"])

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.pull import metrics, qa  # noqa: E402
from app.push import classify, enrich, score  # noqa: E402
from app.sources import screener  # noqa: E402

C = TestClient(main.app)


@pytest.mark.parametrize("head,text,cat", [
    ("Financial Result Updates", "Audited financial results for the quarter", "results"),
    ("Board Meeting Intimation", "to consider unaudited financial results for quarter", "results"),
    ("Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
     "appointment of Mr X as Chief Financial Officer", "management_change"),
    ("Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent",
     "appointment of Secretarial Auditor", "unclassified"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "transcript of earnings conference call", "earnings_call"),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "schedule of meet with investors", "investor_meetings"),
    ("Copy of Newspaper Publication", "financial results published", "unclassified"),
    ("Updates", "signing of contract valued at Rs 6,800 crore", "press_release"),
    ("Outcome of Board Meeting", "approved issue of non-convertible debentures", "fund_raise"),
    ("Credit Rating", "ICRA reaffirmed", "credit_rating"),
    ("Acquisition", "acquire 100% stake", "M&A"),
])
def test_rules(head, text, cat):
    assert classify.rule_classify({"headline": head, "text": text})[0] == cat


def test_outcome_without_keywords_goes_to_model():
    assert classify.rule_classify({"headline": "Outcome of Board Meeting", "text": "outcome of board meeting held today"}) is None


def test_score_tiers():
    it = {"category": "credit_rating", "subtype": "rating", "headline": "Credit Rating", "text": "outlook revised to Negative"}
    assert score.score(it, {"band": "Small"}, None, {})["tier"] == "act"
    it2 = {"category": "credit_rating", "subtype": "rating", "headline": "Credit Rating", "text": "rating reaffirmed"}
    assert score.score(it2, {"band": "Large"}, None, {})["tier"] == "routine"
    assert score.amount_cr("order worth Rs 2,400 crore") == 2400


def test_ebitda_and_card():
    x = json.loads(open("tests/fixtures/llm/results_extract.json").read())
    x["ebitda"] = enrich._ebitda(x)
    assert x["ebitda"][0] == 16400 + 220 + 1400 - 900  # no exceptional line -> nil
    x["finance_costs"] = [None, None, None]  # a genuinely missing input stays unknown
    assert enrich._ebitda(x)[0] is None
    x = json.loads(open("tests/fixtures/llm/results_extract.json").read())
    card = enrich._card_from_lines(x, 1.0, "t")
    rev = card["metrics"][0]
    assert rev["qoq"] == round((65100 / 63400 - 1) * 100, 1) and rev["yoy"] == round((65100 / 60200 - 1) * 100, 1)


def test_metrics_from_screener():
    sc = asyncio.run(screener.company("SAMPLE"))
    assert sc["quarters"]["periods"][-1].startswith(("Sep", "Dec", "Mar", "Jun"))
    assert metrics.fy_label("Sep 2025") == "Q2 FY26" and metrics.fy_label("Mar 2025") == "Q4 FY25"
    fin = metrics.financials(sc)
    assert fin["kpis"][0]["label"] == "Revenue" and fin["kpis"][0]["yoy"] is not None
    tr = metrics.trajectory(sc)
    assert "3y" in tr["cagr"]
    bs = metrics.balance_sheet(sc)
    assert any("Working-capital" in f["text"] for f in bs["flags"])
    cq = metrics.cash_quality(sc)
    assert cq["kpis"]
    assert "[N:quarterly]" in metrics.actuals_table(sc)


def test_bm25():
    ch = [{"text": "revenue growth guidance of 12 percent for FY27", "sid": "S1", "page": 2, "title": "t"},
          {"text": "the weather in mumbai was pleasant", "sid": "S1", "page": 3, "title": "t"}]
    assert qa.bm25("what is the revenue guidance", ch)[0]["page"] == 2


def test_api_digest_and_triage():
    d = C.get("/api/digest?hours=24").json()
    assert d["items"] and d["headline"]
    tiers = {i["tier"] for i in d["items"]}
    assert {"act", "routine"} <= tiers
    first = d["items"][0]
    e = C.get("/api/item/enrich", params={"id": first["id"]}).json()
    assert e["id"] == first["id"]
    r = C.post("/api/triage", json={"id": first["id"], "state": "less"}).json()
    assert r["category_bias"][first["category"]] < 0


def test_api_results_card():
    d = C.get("/api/digest?hours=24").json()
    res = next(i for i in d["items"] if i["category"] == "results" and i["subtype"] != "intimation")
    e = C.get("/api/item/enrich", params={"id": res["id"]}).json()
    assert e["results"]["metrics"][0]["cur"] == 65100 and e["results"]["verdict"]


def test_api_alerts():
    r = C.post("/api/alerts/scan").json()
    assert r["new"] >= 2
    al = C.get("/api/alerts").json()["alerts"]
    assert any(a["kind"] == "volume" for a in al)


def test_research_stream():
    with C.stream("GET", "/api/research/SAMPLE/stream") as r:
        evs = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    keys = [e.get("key") for e in evs if e["type"] == "section"]
    assert {"snapshot", "financials", "trajectory", "balance_sheet", "cash_quality", "business", "promises", "synthesis"} <= set(keys)
    pc = next(e["data"] for e in evs if e.get("key") == "promises")
    assert pc["rows"] and all(r["verdict"] for r in pc["rows"])
    a = C.post("/api/research/SAMPLE/ask", json={"q": "revenue guidance?"}).json()
    assert a["answer"]
