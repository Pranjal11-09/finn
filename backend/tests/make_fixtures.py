"""Generate SYNTHETIC fixtures for tests and offline UI development.

Nothing here is real market data. Names of people are prefixed 'Sample'. Numbers are random walks / invented.
Run: python -I backend/tests/make_fixtures.py
"""
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

F = Path(__file__).parent / "fixtures"
IST = timezone(timedelta(hours=5, minutes=30))
random.seed(7)
now = datetime.now(IST).replace(microsecond=0)

PORT = json.loads((Path(__file__).parents[1] / "portfolio.json").read_text())["portfolio"]

# ---------------- prices -----------------
(F / "prices").mkdir(parents=True, exist_ok=True)
spikes = {"DIXON": (3.4, 6.2), "KAYNES": (2.6, -5.1), "CDSL": (1.4, 4.4), "HAL": (2.2, 1.1)}
for h in PORT:
    px = random.uniform(300, 5000)
    rows = []
    d = now - timedelta(days=380)
    while d <= now:
        if d.weekday() < 5:
            px *= math.exp(random.gauss(0.0004, 0.016))
            rows.append({"d": d.strftime("%Y-%m-%d"), "o": px, "h": px * 1.01, "l": px * 0.99, "c": round(px, 2),
                         "v": int(random.lognormvariate(13, 0.3))})
        d += timedelta(days=1)
    if h["symbol"] in spikes:
        vm, chg = spikes[h["symbol"]]
        avg = sum(r["v"] for r in rows[-21:-1]) / 20
        rows[-1]["v"] = int(avg * vm)
        rows[-1]["c"] = round(rows[-2]["c"] * (1 + chg / 100), 2)
    (F / "prices" / f"{h['symbol']}.json").write_text(json.dumps({"symbol": h["symbol"], "name": h["name"] + " (SAMPLE)",
                                                                   "currency": "INR", "rows": rows}))

# ---------------- announcements -----------------
def t(hours_ago):
    return (now - timedelta(hours=hours_ago)).isoformat()

A = [
    ("TCS", "Financial Result Updates", "SAMPLE: has informed the Exchange regarding Audited Standalone and Consolidated Financial Results for the quarter ended September 30, 2026", 3, "results_q2.pdf"),
    ("DIXON", "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent", "SAMPLE: has informed the Exchange regarding appointment of Mr. Sample Arjun Mehta as Chief Financial Officer (CFO) and Key Managerial Personnel w.e.f. November 14, 2026", 5, "mgmt_cfo.pdf"),
    ("KAYNES", "Credit Rating", "SAMPLE: has informed the Exchange about Credit Rating - ICRA has revised outlook to Negative from Stable on long-term rating", 7, "rating.pdf"),
    ("LT", "Bagging/Receiving of orders/contracts", "SAMPLE: has informed the Exchange regarding receipt of order worth Rs 2,400 crore for a metro rail project", 9, "order.pdf"),
    ("POLYCAB", "Acquisition", "SAMPLE: has informed the Exchange about acquisition of 100% stake in a sample cable maker for Rs 310 crore", 11, "acq.pdf"),
    ("HDFCBANK", "Copy of Newspaper Publication", "SAMPLE: has informed the Exchange about Copy of Newspaper Publication", 4, "news.pdf"),
    ("RELIANCE", "Trading Window-xbrl", "SAMPLE: has informed the Exchange regarding closure of trading window", 6, "tw.pdf"),
    ("ITC", "Certificate under SEBI (Depositories and Participants) Regulations, 2018", "SAMPLE: compliance certificate under Reg 74(5)", 8, "c.pdf"),
    ("SUNPHARMA", "Analysts/Institutional Investor Meet/Con. Call Updates", "SAMPLE: has informed the Exchange about Schedule of meet with institutional investors", 10, "meet.pdf"),
    ("TITAN", "Analysts/Institutional Investor Meet/Con. Call Updates", "SAMPLE: has informed the Exchange about transcript of the earnings conference call for Q2 FY27", 12, "transcript.pdf"),
    ("BAJFINANCE", "Outcome of Board Meeting", "SAMPLE: Board approved raising of funds via issue of non-convertible debentures on private placement basis up to Rs 5,000 crore", 2, "ncd.pdf"),
    ("MARUTI", "Change in Directors/ Key Managerial Personnel/ Auditor/ Compliance Officer/ Share Transfer Agent", "SAMPLE: appointment of Secretarial Auditor for FY27", 13, "aud.pdf"),
    ("BHARTIARTL", "Allotment of ESOP / ESPS", "SAMPLE: allotment of 12,400 equity shares under ESOP scheme", 14, "esop.pdf"),
    ("TRENT", "Board Meeting Intimation", "SAMPLE: board meeting to be held on November 20, 2026 to consider unaudited financial results for the quarter ended September 30, 2026", 15, "bmi.pdf"),
    ("HAL", "Updates", "SAMPLE: has informed the Exchange regarding signing of contract valued at Rs 6,800 crore with the Ministry of Defence", 1, "hal.pdf"),
    ("PERSISTENT", "Shareholders meeting", "SAMPLE: notice of Extra Ordinary General Meeting", 16, "egm.pdf"),
    ("ETERNAL", "Outcome of Board Meeting", "SAMPLE: outcome of board meeting held today", 17, "out.pdf"),
    ("CDSL", "Dividend", "SAMPLE: Board declared interim dividend of Rs 12 per share; record date November 25, 2026", 18, "div.pdf"),
    ("DIXON", "Disclosure under SEBI Takeover Regulations", "SAMPLE: disclosure by promoter group regarding sale of 0.8% equity shares in open market", 19, "sast.pdf"),
    ("SUNPHARMA", "Press Release", "SAMPLE: USFDA warning letter issued to a sample manufacturing facility; company to respond within 15 days", 20, "pr.pdf"),
]
ann = []
for i, (sym, head, text, ago, fn) in enumerate(A):
    name = next(h["name"] for h in PORT if h["symbol"] == sym)
    ann.append({"id": f"nse:fx{i}:{sym}", "symbol": sym, "company": name, "ts": t(ago), "headline": head,
                "text": text, "url": f"https://nsearchives.nseindia.com/corporate/SAMPLE_{fn}", "source": "NSE"})
(F / "announcements.json").write_text(json.dumps(ann, indent=1))

# ---------------- screener sample page -----------------
def tbl(periods, rows):
    th = "".join(f"<th>{p}</th>" for p in periods)
    trs = ""
    for lab, vals in rows.items():
        tds = "".join(f"<td>{'' if v is None else (f'{v:,.0f}' if abs(v) >= 100 else v)}</td>" for v in vals)
        trs += f'<tr><td class="text"><button>{lab}&nbsp;<span>+</span></button></td>{tds}</tr>'
    return f'<table class="data-table"><thead><tr><th></th>{th}</tr></thead><tbody>{trs}</tbody></table>'

qp = []
y, m = 2023, 9
for _ in range(13):
    qp.append(f"{['Mar','Jun','Sep','Dec'][[3,6,9,12].index(m)]} {y}")
    m += 3
    if m > 12:
        m, y = 3, y + 1
sales = [1000 * (1.035 ** i) * (1 + random.uniform(-0.02, 0.02)) for i in range(13)]
opm = [18 + random.uniform(-1.5, 1.5) - i * 0.15 for i in range(13)]
op = [s * o / 100 for s, o in zip(sales, opm)]
oth = [s * 0.01 for s in sales]
inte = [s * 0.012 for s in sales]
dep = [s * 0.035 for s in sales]
pbt = [a + b - c - d for a, b, c, d in zip(op, oth, inte, dep)]
pat = [p * 0.75 for p in pbt]
quarters = tbl(qp, {"Sales": sales, "Expenses": [s - o for s, o in zip(sales, op)], "Operating Profit": op,
                    "OPM %": [round(x) for x in opm], "Other Income": oth, "Interest": inte, "Depreciation": dep,
                    "Profit before tax": pbt, "Tax %": [25] * 13, "Net Profit": pat})
ap = [f"Mar {y}" for y in range(2015, 2027)] + ["TTM"]
asales = [2200 * (1.14 ** i) for i in range(12)] + [4600 * 1.1]
aopm = [15 + i * 0.3 for i in range(12)] + [17]
aop = [s * o / 100 for s, o in zip(asales, aopm)]
apbt = [o * 0.8 for o in aop]
apat = [p * 0.75 for p in apbt]
pl = tbl(ap, {"Sales": asales, "Operating Profit": aop, "OPM %": [round(x) for x in aopm], "Profit before tax": apbt,
              "Net Profit": apat, "EPS in Rs": [p / 10 for p in apat]})
pl += ('<table class="ranges-table"><tr><th colspan="2">Compounded Sales Growth</th></tr>'
       '<tr><td>10 Years:</td><td>14%</td></tr><tr><td>5 Years:</td><td>14%</td></tr></table>')
bp = ap[:-1]
bs = tbl(bp, {"Equity Capital": [100] * 12, "Reserves": [800 * (1.15 ** i) for i in range(12)],
              "Borrowings": [400 + i * 60 for i in range(12)], "CWIP": [20 + i * 25 for i in range(12)],
              "Investments": [100 + i * 10 for i in range(12)]})
cf = tbl(bp, {"Cash from Operating Activity": [p * random.uniform(0.6, 1.2) for p in apat[:-1]],
              "Cash from Investing Activity": [-p * random.uniform(0.4, 1.0) for p in apat[:-1]],
              "Cash from Financing Activity": [-50] * 12, "Net Cash Flow": [5] * 12})
eff = tbl(bp, {"Debtor Days": [60 + i * 2 for i in range(12)], "Inventory Days": [70 + i for i in range(12)],
               "Days Payable": [50] * 12, "Cash Conversion Cycle": [80 + i * 4 for i in range(12)],
               "ROCE %": [18 + i * 0.2 for i in range(12)]})
html = f"""<html><body><h1>Sample Industries Ltd (SYNTHETIC)</h1>
<div class="company-profile"><div class="about"><p>SYNTHETIC SAMPLE COMPANY used for offline tests. Makes widgets for
industrial and consumer customers across two segments.</p></div></div>
<ul id="top-ratios">
<li><span class="name">Market Cap</span><span class="value">₹ <span class="number">52,340</span> Cr.</span></li>
<li><span class="name">Current Price</span><span class="value">₹ <span class="number">1,234</span></span></li>
<li><span class="name">Stock P/E</span><span class="value"><span class="number">48.2</span></span></li>
<li><span class="name">ROCE</span><span class="value"><span class="number">21.4</span> %</span></li>
<li><span class="name">ROE</span><span class="value"><span class="number">17.9</span> %</span></li></ul>
<section id="quarters">{quarters}</section><section id="profit-loss">{pl}</section>
<section id="balance-sheet">{bs}</section><section id="cash-flow">{cf}</section><section id="ratios">{eff}</section>
<section id="documents">
<div class="documents annual-reports"><ul><li><a href="https://example.invalid/annual_report_fy26.pdf">Financial Year 2026 <div>from bse</div></a></li></ul></div>
<div class="documents concalls"><ul>
<li><div>Nov 2026</div><a class="concall-link" href="https://example.invalid/transcript_q2fy27.pdf">Transcript</a></li>
<li><div>Aug 2026</div><a class="concall-link" href="https://example.invalid/transcript_q1fy27.pdf">Transcript</a></li>
</ul></div></section></body></html>"""
(F / "screener").mkdir(exist_ok=True)
(F / "screener" / "SAMPLE.html").write_text(html)

# ---------------- pdf text -----------------
(F / "pdf").mkdir(exist_ok=True)
(F / "pdf" / "results.txt").write_text(
    "SAMPLE LIMITED\fStatement of Audited Consolidated Financial Results for the quarter ended 30-Sep-2026 (Rs in crore)\n"
    "Quarter ended 30.09.2026 30.06.2026 30.09.2025\nRevenue from operations 65,100 63,400 60,200\nOther income 900 1,100 850\n"
    "Finance costs 220 210 200\nDepreciation and amortisation expense 1,400 1,380 1,300\nProfit before tax 16,400 15,800 15,100\n"
    "Net profit for the period 12,300 11,900 11,350")
(F / "pdf" / "transcript.txt").write_text(
    "cover\fModerator: Good evening... SAMPLE CFO: we expect revenue growth of 12-14% for FY27 and EBITDA margin of 18-19%.\f"
    "We are confident demand is recovering. Capex of Rs 1,200 crore planned for FY27.\fAnalyst: margins have fallen...")

# ---------------- llm fixtures -----------------
L = F / "llm"
L.mkdir(exist_ok=True)
(L / "classify.json").write_text(json.dumps({"labels": {f"nse:fx16:ETERNAL": "unclassified"}}))
(L / "results_extract.json").write_text(json.dumps({
    "basis": "consolidated", "unit": "crore", "is_financial": False,
    "periods": {"current": "Q2 FY27", "previous": "Q1 FY27", "year_ago": "Q2 FY26"},
    "revenue": [65100, 63400, 60200], "other_income": [900, 1100, 850], "finance_costs": [220, 210, 200],
    "depreciation": [1400, 1380, 1300], "exceptional": [None, None, None], "pbt": [16400, 15800, 15100],
    "pat": [12300, 11900, 11350], "page": 2}))
(L / "mgmt_extract.json").write_text(json.dumps({"changes": [{
    "person": "Sample Arjun Mehta", "role": "Chief Financial Officer", "action": "appointed", "effective": "14-Nov-2026",
    "reason": None, "profile": "SAMPLE PROFILE: Chartered accountant with 20 years in finance; previously finance head at a sample electronics manufacturer.",
    "prior_roles": ["Sample Electronics Ltd — VP Finance", "Sample Auto Components — Controller"]}]}))
(L / "one_liner.json").write_text(json.dumps({"line": "SAMPLE one-liner: order worth ₹2,400 Cr, ~1.1% of order book; execution over 36 months."}))
(L / "guidance_extract.json").write_text(json.dumps({
    "quarter": "Q2 FY27", "tone": "confident",
    "guidance": [{"metric": "revenue_growth", "target": "12-14%", "period": "FY27", "quote": "we expect revenue growth of 12-14% for FY27", "speaker": "CFO", "page": 2, "quantified": True},
                 {"metric": "margin", "target": "18-19%", "period": "FY27", "quote": "EBITDA margin of 18-19%", "speaker": "CFO", "page": 2, "quantified": True}],
    "claims": [{"topic": "demand", "quote": "We are confident demand is recovering", "page": 3}],
    "pushback": [{"topic": "margins", "gist": "why margins fell three quarters running", "page": 4}]}))
(L / "business_snapshot.json").write_text(json.dumps({
    "what": "SAMPLE: makes widgets for industrial and consumer customers.", "mix_basis": "FY26",
    "segments": [{"name": "Industrial", "share_pct": 62, "note": "B2B contracts", "cite": "S3 p.12"},
                 {"name": "Consumer", "share_pct": 38, "note": "retail distribution", "cite": "S3 p.12"}],
    "drivers": ["Industrial capex cycle [S3 p.14]", "Distribution reach [S3 p.15]"]}))
(L / "dossier_synthesis.json").write_text(json.dumps({
    "promise_vs_delivery": [
        {"promise": "Revenue growth 12-14%", "made": "Q1 FY27", "cite": "S2 p.2", "metric": "revenue_growth", "target": "12-14%", "period": "FY27",
         "actual": "Latest quarter +14.6% YoY", "actual_cite": "N:quarterly", "verdict": "delivered", "comment": "Running at top of range."},
        {"promise": "EBITDA margin 18-19%", "made": "Q1 FY27", "cite": "S2 p.2", "metric": "margin", "target": "18-19%", "period": "FY27",
         "actual": "16% latest quarter", "actual_cite": "N:quarterly", "verdict": "missed", "comment": "Third straight quarter below band."},
        {"promise": "Capex ₹1,200 Cr", "made": "Q2 FY27", "cite": "S1 p.3", "metric": "capex", "target": "₹1,200 Cr", "period": "FY27",
         "actual": "CWIP rising", "actual_cite": "N:annual", "verdict": "pending", "comment": "Year not over."}],
    "scorecard": {"delivered": 1, "partial": 0, "missed": 1, "pending": 1, "unverifiable": 0, "credibility": "medium",
                  "one_line": "SAMPLE: delivers on growth, consistently over-promises on margin."},
    "narrative_vs_numbers": [{"claim": "Demand is recovering", "cite": "S1 p.3", "numbers": "Revenue +14.6% YoY", "num_cite": "N:quarterly", "agree": "yes"},
                             {"claim": "Margins will expand", "cite": "S2 p.2", "numbers": "OPM down ~2pp over 3y", "num_cite": "N:flags", "agree": "no"}],
    "guidance_now": [{"metric": "Revenue growth", "target": "12-14%", "period": "FY27", "cite": "S1 p.2"}],
    "bull": ["SAMPLE bull 1 [N:annual]", "SAMPLE bull 2 [S1 p.3]", "SAMPLE bull 3 [N:flags]"],
    "bear": ["SAMPLE bear 1 [N:quarterly]", "SAMPLE bear 2 [S1 p.4]", "SAMPLE bear 3 [N:flags]"],
    "watch": ["Q3 margin vs 18% floor", "Working-capital days", "Capex execution"]}))
(L / "qa.json").write_text(json.dumps({"answer": "SAMPLE answer: management guided 12-14% growth [S1 p.2].", "confidence": "medium"}))
print("fixtures written to", F)
