"""Promised vs delivered, decided in Python.

The model's only job (upstream, in dossier._guidance) is to *extract* what management said: metric, target,
period, verbatim quote, page. Everything here is deterministic:

  1. parse the target ("18-20%", "high single digit", "at least 12%") into a numeric band
  2. map the metric onto a reported series (OPM % for EBITDA margin, Sales YoY for revenue growth, ...)
  3. work out which quarters the promise covers (FY27 -> Jun..Mar, Q4 FY26 -> Mar, unspecified -> next 4)
  4. compare the reported numbers for those quarters against the band
  5. group repeats across calls and flag when the goalposts moved

Promises whose metric isn't in the financial statements (volumes, store counts, market share) are shown as
"not checkable from financials" instead of being guessed.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .metrics import MONTH_Q, is_financial

TOL = 0.5          # screener prints margins as whole numbers; half a point either way is rounding, not a miss
NEAR = 1.5         # within 1.5pp of the floor is a near miss, not a miss

SERIES_LABEL = {"opm": "EBITDA margin", "net_margin": "PAT margin", "sales_yoy": "Revenue growth",
                "pat_yoy": "PAT growth", "ebitda_yoy": "EBITDA growth"}
SERIES_BASIS = {"opm": "reported operating profit ÷ sales (EBITDA proxy)", "net_margin": "net profit / sales",
                "sales_yoy": "reported sales, YoY", "pat_yoy": "reported net profit, YoY",
                "ebitda_yoy": "reported operating profit, YoY"}
NOT_IN_FS = {"volume": "Volumes aren't in the financial statements",
             "capex": "Capex is only disclosed annually in the cash-flow statement",
             "debt": "Debt targets need the half-yearly balance sheet",
             "other": "Not a line in the financial statements"}


# ---------------------------------------------------------------- quarters
def q_index(fy: int, q: int) -> int:
    return fy * 4 + (q - 1)


def q_label(i: int) -> str:
    return f"Q{i % 4 + 1} FY{str(i // 4)[2:]}"


def period_index(period: str) -> int | None:
    """'Sep 2026' (screener column) -> index of Q2 FY27."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", period or "")
    if not m or m.group(1) not in MONTH_Q:
        return None
    mon, yr = m.group(1), int(m.group(2))
    return q_index(yr + 1 if mon != "Mar" else yr, MONTH_Q[mon])


def _fy(s: str) -> int | None:
    m = re.search(r"fy\s*'?(\d{4}|\d{2})\b", s) or re.search(r"\b20(\d{2})\s*[-/–]\s*(\d{2})\b", s)
    if not m:
        return None
    if m.lastindex == 2:                        # 2026-27
        return 2000 + int(m.group(2))
    y = m.group(1)
    return int(y) if len(y) == 4 else 2000 + int(y)


def made_index(quarter: str, date: str = "") -> int | None:
    """Quarter the call discussed: 'Q2 FY27', 'Q4 and FY26', 'Q3FY26', or from the call date ('Nov 2026')."""
    s = (quarter or "").lower()
    fy = _fy(s)
    m = re.search(r"q\s*([1-4])", s)
    if fy and m:
        return q_index(fy, int(m.group(1)))
    if fy and re.search(r"\bfy", s):
        return q_index(fy, 4)
    d = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", date or "")
    if d:                                       # calls happen 2-8 weeks after quarter end
        mon = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(d.group(1).lower()[:3]) + 1
        yr = int(d.group(2))
        end_month = {1: 12, 2: 12, 3: 12, 4: 3, 5: 3, 6: 3, 7: 6, 8: 6, 9: 6, 10: 9, 11: 9, 12: 9}[mon]
        end_year = yr - 1 if mon <= 3 else yr
        return period_index(f"{['Mar', 'Jun', 'Sep', 'Dec'][[3, 6, 9, 12].index(end_month)]} {end_year}")
    return None


def window(period: str, made: int) -> tuple[list[int], str]:
    """Quarters a promise covers, strictly after the call. Unspecified horizons get the next four quarters."""
    s = (period or "").lower()
    fy = _fy(s)
    q = re.search(r"\bq\s*([1-4])", s)
    h = re.search(r"\bh\s*([12])", s)
    if fy and q:
        w, lab = [q_index(fy, int(q.group(1)))], f"Q{q.group(1)} FY{str(fy)[2:]}"
    elif fy and h:
        a = 1 if h.group(1) == "1" else 3
        w, lab = [q_index(fy, a), q_index(fy, a + 1)], f"H{h.group(1)} FY{str(fy)[2:]}"
    elif fy:
        w, lab = [q_index(fy, k) for k in (1, 2, 3, 4)], f"FY{str(fy)[2:]}"
    else:
        w, lab = [made + k for k in (1, 2, 3, 4)], "next 4 quarters"
    # A full-year target restated mid-year still covers the quarters already reported (that's how YTD is judged);
    # a period that ended before the call is reporting, not a promise.
    return (w if any(i > made for i in w) else []), lab


# ---------------------------------------------------------------- targets
WORDS = [(r"low double[- ]digit", (10, 13)), (r"high single[- ]digit", (7, 9.9)), (r"mid single[- ]digit", (4, 6.9)),
         (r"low single[- ]digit", (1, 3.9)), (r"mid[- ]teens", (14, 16)), (r"high[- ]teens", (17, 19.9)),
         (r"double[- ]digit", (10, None)), (r"high twenties", (27, 29.9)), (r"low teens", (11, 13))]
NUM = r"(\d+(?:\.\d+)?)"


def parse_target(t: str) -> tuple[float | None, float | None] | None:
    """Return (floor, ceiling) in %, or None if the target isn't a percentage level we can test."""
    s = (t or "").lower().replace("–", "-").replace("—", "-")
    if re.search(r"\bbps\b|basis point|₹|\brs\.?\b|crore|\bcr\b|\bbn\b|billion|million|lakh", s):
        return None
    m = re.search(rf"{NUM}\s*%?\s*(?:-|to)\s*{NUM}\s*%", s) or re.search(rf"{NUM}\s*%?\s*(?:-|to)\s*{NUM}\b", s)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        return lo, hi
    m = re.search(rf"{NUM}\s*%", s)
    if m:
        x = float(m.group(1))
        if re.search(r"at least|more than|over|in excess|minimum|upwards|\bplus\b|\+|north of|above|>", s):
            return x, None
        if re.search(r"up to|upto|maximum|below|under|less than|<", s):
            return None  # caps (cost ratios, debt) aren't level promises we test
        return x - 1, x + 1
    for pat, band in WORDS:
        if re.search(pat, s):
            return band
    return None


def series_for(g: dict, lender: bool) -> tuple[str | None, str]:
    """Which reported series tests this promise. Returns (series, reason-if-none)."""
    metric = (g.get("metric") or "other").lower()
    text = f"{g.get('target', '')} {g.get('quote', '')}".lower()
    if metric == "margin":
        if lender:
            return None, "Lender margins (NIM) aren't in the summary financials"
        if re.search(r"gross margin", text):
            return None, "Gross margin isn't in the summary financials"
        if re.search(r"\b(pat|net profit|net) margin", text):
            return "net_margin", ""
        return "opm", ""
    if metric == "revenue_growth":
        if re.search(r"\bvolume", text) and not re.search(r"revenue|sales|top[- ]?line", text):
            return None, NOT_IN_FS["volume"]
        return "sales_yoy", ""
    if metric == "pat_growth":
        return "pat_yoy", ""
    if metric == "other" and re.search(r"ebitda", text) and re.search(r"grow", text):
        return "ebitda_yoy", ""
    return None, NOT_IN_FS.get(metric, NOT_IN_FS["other"])


# ---------------------------------------------------------------- actuals
def _row(rows: dict, *names):
    for n in names:
        if n in rows:
            return rows[n]
    return None


def actuals(sc: dict) -> dict[str, dict[int, float]]:
    q = sc.get("quarters") or {}
    rows, periods = q.get("rows", {}), q.get("periods", [])
    idx = [period_index(p) for p in periods]
    get = lambda *n: {i: v for i, v in zip(idx, _row(rows, *n) or []) if i is not None and v is not None}
    return {"sales": get("Sales", "Revenue"), "opm": get("OPM %", "Financing Margin %"),
            "pat": get("Net Profit"), "op": get("Operating Profit", "Financing Profit")}


def _period_value(series: str, quarters: list[int], A: dict) -> float | None:
    s, pat, op = A["sales"], A["pat"], A["op"]
    if series == "opm":
        if any(i not in op or i not in s for i in quarters):
            return None
        sales = sum(s[i] for i in quarters)
        return round(100 * sum(op[i] for i in quarters) / sales, 1) if sales > 0 else None
    if series == "net_margin":
        a, b = sum(pat.get(i, 0) for i in quarters), sum(s.get(i, 0) for i in quarters)
        return round(a / b * 100, 1) if b and all(i in pat and i in s for i in quarters) else None
    base = {"sales_yoy": s, "pat_yoy": pat, "ebitda_yoy": op}[series]
    if not all(i in base and i - 4 in base for i in quarters):
        return None
    a, b = sum(base[i] for i in quarters), sum(base[i - 4] for i in quarters)
    return round((a / b - 1) * 100, 1) if b > 0 else None


def _fmt(series: str, v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f}%" if series in ("opm", "net_margin") else f"{v:+.1f}%"


def evaluate(series: str, band: tuple, quarters: list[int], A: dict) -> dict:
    lo, hi = band
    have = [i for i in quarters if _period_value(series, [i], A) is not None]
    strip = [{"q": q_label(i), "value": _period_value(series, [i], A)} for i in have]
    for x in strip:
        x["ok"] = lo is None or x["value"] >= lo - TOL
        x["beat"] = hi is not None and x["value"] > hi + TOL
    if not have:
        return {"verdict": "pending", "actual": f"First quarter ({q_label(quarters[0])}) not reported yet", "quarters": []}
    agg = _period_value(series, have, A)
    complete = len(have) == len(quarters)
    span = (f"{q_label(have[0])}" if len(have) == 1 else f"{q_label(have[0])}–{q_label(have[-1])}")
    span += "" if complete else f" ({len(have)} of {len(quarters)} qtrs reported)"
    gap = None if lo is None or agg is None else agg - lo
    if gap is None:
        v = "pending"
    elif gap >= -TOL:
        v = "delivered" if complete else "on_track"
    elif gap >= -NEAR:
        v = "partial" if complete else "at_risk"
    else:
        v = "missed" if complete else "off_track"
    beat = hi is not None and agg is not None and agg > hi + TOL
    return {"verdict": v, "actual": f"{_fmt(series, agg)} over {span}" + (" — above the band" if beat else ""),
            "value": agg, "complete": complete, "quarters": strip}


def _band_text(band: tuple | None, raw: str) -> str:
    if not band:
        return raw
    lo, hi = band
    f = lambda x: f"{x:g}"
    return f"{f(lo)}–{f(hi)}%" if lo is not None and hi is not None else f"≥{f(lo)}%" if lo is not None else raw


# ---------------------------------------------------------------- main
def check(gs: list[dict], sc: dict, transcripts: list[dict] | None = None) -> dict:
    """gs: per-transcript extractions (dossier._guidance output), any order. Returns the promises section."""
    lender = is_financial(sc)
    A = actuals(sc)
    dates = {d["sid"]: d.get("date", "") for d in (transcripts or [])}
    latest_reported = max(A["sales"]) if A["sales"] else None
    mentions = []
    for g in gs:
        if g.get("error"):
            continue
        made = made_index(g.get("quarter", ""), dates.get(g["sid"], ""))
        if made is None:
            continue
        for x in g.get("guidance", []) or []:
            if not isinstance(x, dict) or not x.get("quote"):
                continue
            series, reason = series_for(x, lender)
            band = parse_target(str(x.get("target", "")))
            w, wlab = window(str(x.get("period", "")), made)
            if not w:
                continue                             # restating a period that's already over is reporting, not a promise
            mentions.append({"made": made, "series": series, "reason": reason, "band": band, "window": w,
                             "period": wlab, "metric": (x.get("metric") or "other").lower(),
                             "target_raw": str(x.get("target", "")), "quote": x.get("quote", ""),
                             "cite": f"{g['sid']} p.{x.get('page')}" if x.get("page") else g["sid"]})

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for m in mentions:
        key = (m["series"] or m["metric"], m["band"] if m["band"] else m["target_raw"].lower()[:40])
        groups[key].append(m)

    rows = []
    for (topic, _), ms in groups.items():
        ms.sort(key=lambda m: m["made"])
        last = ms[-1]
        label = (SERIES_LABEL[last["series"]] if last["series"] and last["band"]
                 else last["metric"].replace("_", " ").capitalize())
        row = {"promise": f"{label} {_band_text(last['band'], last['target_raw'])}" + (
                   f" for {last['period']}" if last["period"] != "next 4 quarters" else ""),
               "metric": label, "topic": topic, "target": _band_text(last["band"], last["target_raw"]),
               "period": last["period"], "quote": last["quote"], "cite": last["cite"],
               "made": q_label(ms[0]["made"]) + " call",
               "said_in": list({q_label(m["made"]): {"call": q_label(m["made"]), "cite": m["cite"]} for m in ms}.values()),
               "repeats": len({m["made"] for m in ms})}
        if last["series"] and last["band"]:
            row.update(evaluate(last["series"], last["band"], last["window"], A))
            row["basis"] = SERIES_BASIS[last["series"]]
            # every quarter since the promise was first made: did they live inside the band all along?
            since = [i for i in range(ms[0]["made"] + 1, (latest_reported or ms[0]["made"]) + 1)]
            row["track"] = evaluate(last["series"], last["band"], since, A)["quarters"] if since else []
            misses = [x["q"] for x in row["track"] if not x["ok"]]
            if row["verdict"] in ("delivered", "on_track") and misses:
                row["comment"] = f"Below the floor in {', '.join(misses)}."
            elif row["verdict"] in ("missed", "off_track", "partial", "at_risk"):
                row["comment"] = f"Needs ≥{last['band'][0]:g}%; " + (f"missed in {', '.join(misses)}." if misses else "short on aggregate.")
        else:
            why = last["reason"] or "Target isn't a percentage level"
            row.update({"verdict": "unverifiable", "actual": why, "quarters": [], "track": []})
        rows.append(row)

    # moved goalposts: same topic, a later call states a lower floor (or narrows the top end)
    revisions = []
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for m in mentions:
        if m["band"]:
            by_topic[m["series"] or m["metric"]].append(m)
    for topic, ms in by_topic.items():
        ms.sort(key=lambda m: m["made"])
        for a, b in zip(ms, ms[1:]):
            (alo, ahi), (blo, bhi) = a["band"], b["band"]
            if a["made"] == b["made"] or alo is None or blo is None:
                continue
            label = SERIES_LABEL.get(b["series"], b["metric"].replace("_", " ").capitalize())
            frm, to = _band_text(a["band"], ""), _band_text(b["band"], "")
            if blo < alo - 0.01:
                revisions.append({"topic": label, "direction": "lowered",
                                  "text": f"{label} guidance cut from {frm} to {to} in the {q_label(b['made'])} call",
                                  "cite": b["cite"], "prev_cite": a["cite"]})
            elif ahi is not None and bhi is not None and bhi < ahi - 0.01:
                revisions.append({"topic": label, "direction": "narrowed",
                                  "text": f"{label} guidance narrowed from {frm} to {to} (top end dropped) in the "
                                          f"{q_label(b['made'])} call", "cite": b["cite"], "prev_cite": a["cite"]})
            elif blo > alo + 0.01:
                revisions.append({"topic": label, "direction": "raised",
                                  "text": f"{label} guidance raised from {_band_text(a['band'], '')} to {_band_text(b['band'], '')} "
                                          f"in the {q_label(b['made'])} call", "cite": b["cite"], "prev_cite": a["cite"]})
    # de-dupe identical revision lines
    seen, revs = set(), []
    for r in revisions:
        if r["text"] not in seen:
            seen.add(r["text"])
            revs.append(r)

    order = {"missed": 0, "off_track": 1, "partial": 2, "at_risk": 3, "delivered": 4, "on_track": 5, "pending": 6,
             "unverifiable": 7}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -r["repeats"]))
    return {"rows": rows, "revisions": revs, "scorecard": scorecard(rows, revs),
            "method": "Targets and quotes are extracted by a model; every verdict is computed in Python from reported "
                      "quarterly numbers. Margins use reported OPM % as the EBITDA proxy, revenue-weighted across quarters."}


def scorecard(rows: list[dict], revs: list[dict]) -> dict:
    c = defaultdict(int)
    for r in rows:
        c[r["verdict"]] += 1
    good, half, bad = c["delivered"] + c["on_track"], c["partial"] + c["at_risk"], c["missed"] + c["off_track"]
    checkable = good + half + bad
    if not checkable:
        cred, line = "n/a", "No promise could be checked against reported numbers."
    else:
        s = (good + 0.5 * half) / checkable - 0.1 * sum(1 for r in revs if r["direction"] == "lowered") \
            - 0.05 * sum(1 for r in revs if r["direction"] == "narrowed")
        cred = "high" if s >= 0.75 else "medium" if s >= 0.45 else "low"
        if checkable < 2 and cred == "high":
            cred = "medium"          # one data point isn't a track record
        line = f"{good} of {checkable} checkable promise{'s' if checkable > 1 else ''} held"
        worst = next((r for r in rows if r["verdict"] in ("missed", "off_track", "partial", "at_risk")), None)
        slipped = next((r for r in rows if r["verdict"] in ("delivered", "on_track") and r.get("comment")), None)
        if worst:
            line += f"; {worst['promise'].split(' for ')[0]} {worst['verdict'].replace('_', ' ')} ({worst['actual'].split(' over ')[0]})"
        elif slipped:
            line += f"; {slipped['metric']} dipped below the floor in {slipped['comment'].split(' in ')[-1].rstrip('.')}"
        lowered = [r for r in revs if r["direction"] in ("lowered", "narrowed")]
        if lowered:
            line += f"; {lowered[0]['topic']} guidance {lowered[0]['direction'].replace('lowered', 'cut')}"
        line += "."
    return {**{k: c[k] for k in ("delivered", "on_track", "partial", "at_risk", "missed", "off_track", "pending",
                                 "unverifiable")}, "checkable": checkable, "credibility": cred, "one_line": line}
