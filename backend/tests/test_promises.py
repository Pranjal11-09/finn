"""Promise checker: deterministic verdicts on hand-built quarters."""
from app.pull import promises as P


def _sc(opm, sales, start=("Jun", 2025)):
    months = ["Jun", "Sep", "Dec", "Mar"]
    m, y = months.index(start[0]), start[1]
    periods = []
    for _ in opm:
        periods.append(f"{months[m]} {y}")
        m += 1
        if m == 4:
            m = 0
        if months[m] == "Mar":
            y += 1
    return {"quarters": {"periods": periods, "rows": {"Sales": sales, "OPM %": opm, "Net Profit": [s * 0.1 for s in sales],
                                                      "Operating Profit": [s * o / 100 for s, o in zip(sales, opm)]}},
            "pl": {"rows": {}}, "bs": {"rows": {}}}


def test_parse_targets():
    assert P.parse_target("18-20%") == (18, 20)
    assert P.parse_target("double-digit") == (10, None)
    assert P.parse_target("at least 15%") == (15, None)
    assert P.parse_target("₹2,000 Cr") is None and P.parse_target("300 bps") is None


def test_quarters():
    mi = P.made_index("Q2 FY27")
    assert P.q_label(mi) == "Q2 FY27"
    assert [P.q_label(i) for i in P.window("FY27", mi)[0]] == ["Q1 FY27", "Q2 FY27", "Q3 FY27", "Q4 FY27"]
    assert P.window("FY26", mi)[0] == []          # already over -> reporting, not a promise
    assert P.q_label(P.made_index("", "Nov 2026")) == "Q2 FY27"
    assert P.period_index("Mar 2026") == P.made_index("Q4 FY26")


def test_margin_band_verdicts_and_goalposts():
    # Jun25..Sep26: margins 19,19,20,19 (FY26 in band), then 21, 16 in FY27
    sc = _sc([19, 19, 20, 19, 21, 16], [100] * 6)
    g = lambda sid, q, tgt, per: {"sid": sid, "quarter": q, "guidance": [
        {"metric": "margin", "target": tgt, "period": per, "quote": f"margin {tgt}", "page": 3}]}
    out = P.check([g("S2", "Q4 FY25", "18-20%", "FY26"), g("S1", "Q1 FY27", "17-19%", "FY27")], sc)
    by = {r["target"]: r for r in out["rows"]}
    assert by["18–20%"]["verdict"] == "delivered"
    assert by["17–19%"]["verdict"] == "on_track" and "Q2 FY27" in by["17–19%"]["comment"]
    assert any(r["direction"] == "lowered" for r in out["revisions"])


def test_miss_and_unverifiable():
    sc = _sc([12, 12, 12, 12, 12, 12], [100, 100, 100, 100, 102, 102])
    gs = [{"sid": "S1", "quarter": "Q4 FY26", "guidance": [
        {"metric": "revenue_growth", "target": "12-14%", "period": "FY27", "quote": "revenue growth 12-14%", "page": 2},
        {"metric": "volume", "target": "8-10%", "period": "FY27", "quote": "volume growth 8-10%", "page": 2}]}]
    out = P.check(gs, sc)
    v = {r["metric"]: r["verdict"] for r in out["rows"]}
    assert v["Revenue growth"] == "off_track" and v["Volume"] == "unverifiable"
    assert out["scorecard"]["checkable"] == 1


def test_operating_margin_combines_profit_and_sales_before_rounding():
    from app.pull.promises import _period_value
    assert _period_value("opm", [1, 2], {"sales": {1: 10542, 2: 9977},
                         "opm": {1: 21, 2: 16}, "op": {1: 2169, 2: 1557}, "pat": {}}) == 18.2
