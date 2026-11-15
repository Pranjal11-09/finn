"""Deterministic research sections. Python does every number; flags are rules with thresholds stated in-line.
The model later *reads* these, it never produces them."""
from __future__ import annotations

import re

MONTH_Q = {"Jun": 1, "Sep": 2, "Dec": 3, "Mar": 4}


def fy_label(period: str) -> str:
    """'Sep 2025' -> 'Q2 FY26'; 'Mar 2025' (annual col) handled by caller."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", period or "")
    if not m or m.group(1) not in MONTH_Q:
        return period
    mon, yr = m.group(1), int(m.group(2))
    fy = yr + 1 if mon != "Mar" else yr
    return f"Q{MONTH_Q[mon]} FY{str(fy)[2:]}"


def _row(tbl: dict, *names: str) -> list | None:
    rows = tbl.get("rows", {})
    for n in names:
        if n in rows:
            return rows[n]
    for n in names:   # loose match
        for k, v in rows.items():
            if k.lower().startswith(n.lower()):
                return v
    return None


def _last(v, i=-1):
    try:
        x = v[i]
        return x
    except (TypeError, IndexError):
        return None


def _cagr(a, b, years):
    try:
        if a and b and a > 0 and b > 0 and years > 0:
            return round(((b / a) ** (1 / years) - 1) * 100, 1)
    except (TypeError, ZeroDivisionError):
        pass
    return None


def _pct(a, b):
    try:
        return round((a / b - 1) * 100, 1) if a is not None and b and b > 0 else None
    except TypeError:
        return None


def is_financial(sc: dict) -> bool:
    return bool(_row(sc["pl"], "Financing Profit") or _row(sc["bs"], "Deposits"))


def _annual_cols(tbl: dict) -> tuple[list[str], int]:
    """Drop TTM column for annual series; return periods and slice end."""
    p = tbl.get("periods", [])
    end = len(p) - 1 if p and p[-1].upper().startswith("TTM") else len(p)
    return p[:end], end


def snapshot(sc: dict) -> dict:
    r = sc.get("ratios", {})
    kp = [("Market Cap", "Market Cap", "₹ Cr"), ("Price", "Current Price", "₹"), ("P/E", "Stock P/E", "x"),
          ("ROCE", "ROCE", "%"), ("ROE", "ROE", "%"), ("Div. yield", "Dividend Yield", "%"),
          ("Book value", "Book Value", "₹")]
    return {"title": "At a glance", "about": sc.get("about", ""),
            "kpis": [{"label": a, "value": r.get(b), "unit": u} for a, b, u in kp if r.get(b) is not None]}


def financials(sc: dict) -> dict:
    fin = is_financial(sc)
    q = sc["quarters"]
    rev = _row(q, "Sales", "Revenue")
    op = _row(q, "Operating Profit", "Financing Profit")
    opm = _row(q, "OPM %", "Financing Margin %")
    pat = _row(q, "Net Profit")
    pbt = _row(q, "Profit before tax")
    periods = q.get("periods", [])
    if not rev or len(periods) < 5:
        return {"title": "Latest quarter", "kpis": [], "flags": [{"tone": "neutral", "text": "Quarterly data unavailable"}]}
    cur = fy_label(periods[-1])
    k = []
    for lab, v in (("Revenue", rev), ("EBITDA" if not fin else "Op. profit", op), ("PBT", pbt), ("PAT", pat)):
        if v:
            k.append({"label": lab, "value": _last(v), "unit": "₹ Cr", "yoy": _pct(_last(v), _last(v, -5)),
                      "qoq": _pct(_last(v), _last(v, -2))})
    if opm:
        k.append({"label": "Margin", "value": _last(opm), "unit": "%", "delta_pp": (
            round(_last(opm) - _last(opm, -5), 1) if _last(opm) is not None and _last(opm, -5) is not None else None)})
    # TTM from the 4 latest quarters
    ttm = lambda v: sum(x for x in v[-4:] if x is not None) if v and len(v) >= 4 else None
    return {"title": f"Latest quarter · {cur}", "period": cur, "kpis": k,
            "ttm": {"revenue": ttm(rev), "pat": ttm(pat)},
            "quarterly": {"periods": [fy_label(p) for p in periods[-12:]], "revenue": (rev or [])[-12:],
                          "opm": (opm or [])[-12:], "pat": (pat or [])[-12:]}}


def trajectory(sc: dict) -> dict:
    pl = sc["pl"]
    periods, end = _annual_cols(pl)
    rev = (_row(pl, "Sales", "Revenue") or [])[:end]
    op = (_row(pl, "Operating Profit", "Financing Profit") or [])[:end]
    opm = (_row(pl, "OPM %", "Financing Margin %") or [])[:end]
    pat = (_row(pl, "Net Profit") or [])[:end]
    eps = (_row(pl, "EPS in Rs") or [])[:end]
    flags = []
    n = len(rev)
    out = {"title": "Trajectory", "periods": [p.replace("Mar ", "FY") for p in periods][-10:],
           "series": {"Revenue": rev[-10:], "EBITDA": op[-10:], "Margin %": opm[-10:], "PAT": pat[-10:], "EPS": eps[-10:]},
           "cagr": {}}
    for yrs in (3, 5):
        if n > yrs:
            out["cagr"][f"{yrs}y"] = {"Revenue": _cagr(rev[-1 - yrs], rev[-1], yrs), "PAT": _cagr(pat[-1 - yrs], pat[-1], yrs),
                                      "EPS": _cagr(eps[-1 - yrs], eps[-1], yrs) if eps else None}
    c3 = out["cagr"].get("3y", {})
    if c3.get("Revenue") is not None and c3.get("PAT") is not None:
        gap = c3["PAT"] - c3["Revenue"]
        if gap > 4:
            flags.append({"tone": "good", "text": f"Profit compounding faster than sales (3y PAT {c3['PAT']}% vs revenue {c3['Revenue']}%) — operating leverage."})
        elif gap < -4:
            flags.append({"tone": "bad", "text": f"Profit lagging sales (3y PAT {c3['PAT']}% vs revenue {c3['Revenue']}%) — margins compressing."})
    if len(opm) >= 4 and all(x is not None for x in opm[-4:]):
        d = opm[-1] - sum(opm[-4:-1]) / 3
        if abs(d) >= 1.5:
            flags.append({"tone": "good" if d > 0 else "bad",
                          "text": f"Margin {opm[-1]:.0f}% is {abs(d):.1f}pp {'above' if d > 0 else 'below'} its prior 3-year average."})
    if c3.get("EPS") is not None and c3.get("PAT") is not None and c3["PAT"] - c3["EPS"] > 3:
        flags.append({"tone": "bad", "text": f"EPS growth ({c3['EPS']}%) trails PAT growth ({c3['PAT']}%) — dilution."})
    out["flags"] = flags
    return out


def balance_sheet(sc: dict) -> dict:
    bs, eff = sc["bs"], sc["eff"]
    periods, end = _annual_cols(bs)
    fin = is_financial(sc)
    eq_cap = (_row(bs, "Equity Capital") or [])[:end]
    res = (_row(bs, "Reserves") or [])[:end]
    debt = (_row(bs, "Borrowings", "Borrowing") or [])[:end]
    cwip = (_row(bs, "CWIP") or [])[:end]
    inv = (_row(bs, "Investments") or [])[:end]
    equity = [(a or 0) + (b or 0) for a, b in zip(eq_cap, res)]
    de = [round(d / e, 2) if d is not None and e else None for d, e in zip(debt, equity)]
    flags, kpis = [], []
    if equity:
        kpis.append({"label": "Net worth", "value": equity[-1], "unit": "₹ Cr"})
    if debt:
        kpis.append({"label": "Borrowings", "value": debt[-1], "unit": "₹ Cr"})
    if de and de[-1] is not None and not fin:
        kpis.append({"label": "Debt / Equity", "value": de[-1], "unit": "x"})
        if de[-1] > 1:
            flags.append({"tone": "bad", "text": f"Leverage is high: D/E {de[-1]}x."})
        elif de[-1] < 0.1:
            flags.append({"tone": "good", "text": f"Practically debt-free (D/E {de[-1]}x)."})
        if len(de) >= 4 and de[-4] is not None and de[-1] - de[-4] > 0.3:
            flags.append({"tone": "bad", "text": f"Leverage rising: D/E {de[-4]}x → {de[-1]}x over 3 years."})
    if cwip and equity and cwip[-1] and equity[-1] and cwip[-1] / equity[-1] > 0.1:
        flags.append({"tone": "neutral", "text": f"₹{cwip[-1]:,.0f} Cr capex in progress (CWIP) — {cwip[-1] / equity[-1] * 100:.0f}% of net worth."})
    wc = {}
    ep, eend = _annual_cols(eff)
    for lab in ("Debtor Days", "Inventory Days", "Days Payable", "Cash Conversion Cycle", "Working Capital Days"):
        v = _row(eff, lab)
        if v:
            wc[lab] = v[:eend][-6:]
    ccc = wc.get("Cash Conversion Cycle") or wc.get("Working Capital Days")
    if ccc and len(ccc) >= 4 and ccc[-1] is not None and ccc[-4] is not None:
        d = ccc[-1] - ccc[-4]
        if abs(d) >= 10:
            flags.append({"tone": "bad" if d > 0 else "good",
                          "text": f"Working-capital cycle {'lengthened' if d > 0 else 'shortened'} by {abs(d):.0f} days over 3 years ({ccc[-4]:.0f} → {ccc[-1]:.0f})."})
    if fin:
        flags.append({"tone": "neutral", "text": "Lender: leverage and working-capital ratios don't apply the usual way; read capital adequacy in the AR."})
    return {"title": "Balance sheet", "kpis": kpis, "periods": [p.replace("Mar ", "FY") for p in periods][-6:],
            "series": {"Borrowings": debt[-6:], "Net worth": equity[-6:], "D/E": de[-6:], "CWIP": cwip[-6:],
                       "Investments": inv[-6:]},
            "wc": {"periods": [p.replace("Mar ", "FY") for p in ep[:eend]][-6:], **wc}, "flags": flags}


def cash_quality(sc: dict) -> dict:
    cf, pl = sc["cf"], sc["pl"]
    periods, end = _annual_cols(cf)
    cfo = (_row(cf, "Cash from Operating Activity") or [])[:end]
    cfi = (_row(cf, "Cash from Investing Activity") or [])[:end]
    _, pend = _annual_cols(pl)
    pat_all = (_row(pl, "Net Profit") or [])[:pend]
    # align PAT to cash-flow years by period label
    pmap = dict(zip(_annual_cols(pl)[0], pat_all))
    pat = [pmap.get(p) for p in periods]
    conv = [round(c / p, 2) if c is not None and p and p > 0 else None for c, p in zip(cfo, pat)]
    fcf = [round(c + i) if c is not None and i is not None else None for c, i in zip(cfo, cfi)]
    flags, kpis = [], []
    n = min(5, len(cfo))
    if n:
        s_cfo = sum(x for x in cfo[-n:] if x is not None)
        s_pat = sum(x for x in pat[-n:] if x is not None)
        if s_pat > 0:
            r = round(s_cfo / s_pat, 2)
            kpis.append({"label": f"CFO / PAT ({n}y)", "value": r, "unit": "x"})
            if r < 0.7:
                flags.append({"tone": "bad", "text": f"Only {r * 100:.0f}% of {n}-year profit showed up as operating cash — check receivables/inventory."})
            elif r >= 1.0:
                flags.append({"tone": "good", "text": f"Profits are fully backed by cash ({r:.2f}x over {n} years)."})
        s_fcf = sum(x for x in fcf[-n:] if x is not None)
        kpis.append({"label": f"FCF proxy ({n}y)", "value": s_fcf, "unit": "₹ Cr"})
        neg = sum(1 for x in fcf[-n:] if x is not None and x < 0)
        if neg >= 3:
            flags.append({"tone": "bad", "text": f"Operating cash didn't cover investing outflows in {neg} of the last {n} years."})
    if is_financial(sc):
        flags.append({"tone": "neutral", "text": "Lender: operating cash flow mixes loan growth with earnings; conversion ratio is not meaningful."})
    return {"title": "Cash quality", "kpis": kpis, "periods": [p.replace("Mar ", "FY") for p in periods][-6:],
            "series": {"CFO": cfo[-6:], "PAT": pat[-6:], "CFO/PAT": conv[-6:], "FCF proxy": fcf[-6:]},
            "note": "FCF proxy = cash from operations + cash from investing (includes treasury moves).", "flags": flags}


def actuals_table(sc: dict) -> str:
    """Compact text table of quarterly + annual actuals for the reasoning model (and its citations)."""
    q = sc["quarters"]
    periods = q.get("periods", [])[-10:]
    rev = (_row(q, "Sales", "Revenue") or [])[-10:]
    opm = (_row(q, "OPM %", "Financing Margin %") or [])[-10:]
    pat = (_row(q, "Net Profit") or [])[-10:]
    full_rev = _row(q, "Sales", "Revenue") or []
    lines = ["[N:quarterly] period | revenue ₹Cr | revenue YoY% | EBITDA margin % | PAT ₹Cr"]
    off = len(full_rev) - len(rev)
    for i, p in enumerate(periods):
        j = off + i
        yoy = _pct(full_rev[j], full_rev[j - 4]) if j >= 4 else None
        lines.append(f"{p} ({fy_label(p)}) | {rev[i]} | {yoy} | {opm[i] if i < len(opm) else None} | {pat[i] if i < len(pat) else None}")
    pl = sc["pl"]
    ap, end = _annual_cols(pl)
    arev = (_row(pl, "Sales", "Revenue") or [])[:end]
    aopm = (_row(pl, "OPM %", "Financing Margin %") or [])[:end]
    apat = (_row(pl, "Net Profit") or [])[:end]
    lines.append("[N:annual] FY | revenue | YoY% | margin % | PAT")
    for i in range(max(0, len(ap) - 5), len(ap)):
        lines.append(f"{ap[i].replace('Mar ', 'FY')} | {arev[i] if i < len(arev) else None} | "
                     f"{_pct(arev[i], arev[i - 1]) if 0 < i < len(arev) else None} | {aopm[i] if i < len(aopm) else None} | "
                     f"{apat[i] if i < len(apat) else None}")
    return "\n".join(lines)


def flags_text(sections: list[dict]) -> str:
    return "\n".join(f"- [{s['title']}] {f['text']}" for s in sections for f in s.get("flags", []))
