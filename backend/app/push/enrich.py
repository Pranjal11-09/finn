"""Turn an important filing into something readable in 5 seconds.

results            -> headline numbers card (Revenue / EBITDA / PBT / PAT, QoQ & YoY), LLM reads the filing,
                      Python does all arithmetic, screener's quarterly table is the cross-check / fallback.
management_change  -> who is the person: profile from the filing's Reg-30 annexure, optional web enrichment.
everything 'act'   -> one-line "so what" from the first pages of the filing.
"""
from __future__ import annotations

import re
import math
from urllib.parse import quote_plus

import httpx

from .. import config, db, llm
from ..pull.metrics import is_financial as _is_lender
from ..sources import pdftext, screener

UNIT_TO_CR = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lakhs": 0.01, "million": 0.1, "mn": 0.1, "thousand": 0.0001,
              "billion": 100.0}

RESULTS_SYS = ("You extract numbers from Indian listed-company quarterly results filings. Copy numbers exactly as "
               "printed; never compute or guess. If a value is not printed, use null.")

RESULTS_PROMPT = """From the results statement below, extract the CONSOLIDATED figures if a consolidated statement is present, else standalone.
Use the three quarter columns: the current quarter, the immediately preceding quarter, and the same quarter of the previous year.
Return JSON:
{{"basis":"consolidated|standalone","unit":"crore|lakh|million|thousand","is_financial": true/false,
 "periods":{{"current":"label","previous":"label","year_ago":"label"}},
 "revenue":[cur,prev,yago],          // 'Revenue from operations' (for banks: 'Total income' or 'Interest earned')
 "other_income":[cur,prev,yago],
 "finance_costs":[cur,prev,yago],
 "depreciation":[cur,prev,yago],
 "exceptional":[cur,prev,yago],      // exceptional items, signed as printed; [0,0,0] if the statement has no exceptional line
 "pbt":[cur,prev,yago],              // profit before tax
 "pat":[cur,prev,yago],              // net profit for the period (attributable to owners if shown)
 "page": <1-based page number you used>}}

FILING TEXT:
{text}"""


def _n(v):
    """Model output -> float. Handles '9,525.15', '(123.4)' (negative), '₹ 1,200', '-', None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    t = str(v).strip().replace(",", "").replace("₹", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if t.lower() in ("", "-", "--", "—", "–", "na", "n/a", "nil", "null"):
        return None
    try:
        x = float(t)
    except ValueError:
        return None
    return (-x if neg else x) if math.isfinite(x) else None


def _clean_lines(x: dict) -> dict:
    """Normalise every [cur, prev, yago] list the model returned into floats/None (length 3)."""
    for k in ("revenue", "other_income", "finance_costs", "depreciation", "exceptional", "pbt", "pat"):
        v = x.get(k)
        if not isinstance(v, list):
            v = [None, None, None]
        x[k] = [_n(a) for a in (v + [None, None, None])[:3]]
    return x


def _pct(a, b):
    try:
        return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None
    except TypeError:
        return None


def _card_from_lines(lines: dict, mult: float, source: str) -> dict:
    def col(k, i):
        v = (lines.get(k) or [None, None, None])
        v = v[i] if i < len(v) else None
        v = _n(v)
        return None if v is None else v * mult

    metrics = []
    for key, label in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pbt", "PBT"), ("pat", "PAT")):
        cur, prev, yago = col(key, 0), col(key, 1), col(key, 2)
        metrics.append({"key": key, "label": label, "cur": cur, "prev": prev, "yago": yago,
                        "qoq": _pct(cur, prev), "yoy": _pct(cur, yago)})
    rev = metrics[0]
    for m in metrics[1:3]:
        m["margin"] = round(m["cur"] / rev["cur"] * 100, 1) if m["cur"] is not None and rev["cur"] else None
        m["margin_yago"] = round(m["yago"] / rev["yago"] * 100, 1) if m["yago"] is not None and rev["yago"] else None
    return {"metrics": metrics, "source": source}


def _ebitda(lines: dict) -> list:
    """Operating EBITDA = PBT + finance costs + D&A - other income - exceptional (exceptional printed signed)."""
    out = []
    for i in range(3):
        g = lambda k: _n(((lines.get(k) or [None] * 3) + [None] * 3)[i])
        pbt = g("pbt")
        # A results statement without an exceptional-items line has none: nil, not unknown.
        if pbt is None or any(g(k) is None for k in ("finance_costs", "depreciation", "other_income")):
            out.append(None)
            continue
        out.append(pbt + (g("finance_costs") or 0) + (g("depreciation") or 0) - (g("other_income") or 0)
                   - (g("exceptional") or 0))
    return out


_MON = {m: m[:3].title() for m in ("january february march april may june july august september october "
                                   "november december").split()}


def _norm_period(p) -> str | None:
    """'30th September 2026' / 'Q2 FY27 (Sep-26)' / 'Sep 2026' -> 'Sep 2026'."""
    t = str(p or "").lower()
    fiscal = re.search(r"\bq([1-4])\s*fy\s*(\d{2}|20\d{2})\b", t)
    if fiscal:
        q, y = int(fiscal[1]), int(fiscal[2])
        y = y + 2000 if y < 100 else y
        return f"{['Jun', 'Sep', 'Dec', 'Mar'][q - 1]} {y if q == 4 else y - 1}"
    mon = next((v for k, v in _MON.items() if k in t or re.search(rf"\b{k[:3]}\b", t)), None)
    yr = re.search(r"(20\d{2})", t) or re.search(r"[-' ](\d{2})\b", t)
    if not mon or not yr:
        return None
    y = yr.group(1)
    return f"{mon} {y if len(y) == 4 else '20' + y}"


def _norm_periods(ps) -> tuple | None:
    if not isinstance(ps, dict):
        return None
    out = tuple(_norm_period(ps.get(k)) for k in ("current", "previous", "year_ago"))
    return out if all(out) else None


def screener_card(sc: dict) -> dict | None:
    q = sc.get("quarters") or {}
    rows, periods = q.get("rows", {}), q.get("periods", [])
    if len(periods) < 5:
        return None
    pick = lambda *names: next((rows[n] for n in names if n in rows), None)
    rev = pick("Sales", "Revenue")
    op = pick("Operating Profit", "Financing Profit")
    pbt = pick("Profit before tax")
    pat = pick("Net Profit")
    if not rev:
        return None
    lines = {k: [v[-1], v[-2], v[-5]] if v else [None] * 3 for k, v in
             (("revenue", rev), ("ebitda", op), ("pbt", pbt), ("pat", pat))}
    card = _card_from_lines(lines, 1.0, "screener.in quarterly table")
    card["periods"] = {"current": periods[-1], "previous": periods[-2], "year_ago": periods[-5]}
    card["unit"] = "₹ Cr"
    card["basis"] = sc.get("basis", "consolidated")
    return card


def validate_extraction(x: dict, pages: list[str], selected: list[int]) -> dict:
    """Reject unsupported metadata/numbers; presence is not proof of the right row or column."""
    unit = str(x.get("unit", "")).lower().strip()
    page = x.get("page")
    if unit not in UNIT_TO_CR or x.get("basis") not in ("consolidated", "standalone"):
        raise ValueError("Unknown unit or reporting basis")
    if type(page) is not int or page - 1 not in selected or not _norm_periods(x.get("periods")):
        raise ValueError("Missing period labels or source page")
    printed = {_n(v) for v in re.findall(r"(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?", pages[page - 1])}
    x = _clean_lines(x)
    for key in ("revenue", "other_income", "finance_costs", "depreciation", "exceptional", "pbt", "pat"):
        for value in x[key]:
            if value is not None and not (key == "exceptional" and value == 0) and value not in printed:
                raise ValueError("Extracted number is absent from the cited page")
    return x


async def results_card(item: dict) -> dict:
    key = "validated-v4:" + item["id"]
    hit = db.kv_get("card_results", key)
    if hit:
        return hit[0]
    card = None
    sc = None
    try:
        sc = await screener.company(item["symbol"])
    except Exception:
        pass
    # Lender or not is a fact about the company, not something to ask the model per filing.
    lender = _is_lender(sc) if sc else None
    pgs = await pdftext.pages(item.get("url", ""), max_pages=30)
    if pgs:
        idx = pdftext.rank_pages(pgs, {"revenue from operations": 4, "profit before tax": 3, "quarter ended": 2,
                                       "consolidated": 1.5, "total income": 2, "finance costs": 2,
                                       "depreciation": 1}, k=2)
        text = "\n\n".join(f"[page {i + 1}]\n{pgs[i][:7000]}" for i in idx)
        if text.strip():
            try:
                x = await llm.call("results_extract", RESULTS_PROMPT.format(text=text), system=RESULTS_SYS,
                                   tier="cheap", version="v3")
                x = validate_extraction(x, pgs, idx)
                mult = UNIT_TO_CR[str(x["unit"]).lower().strip()]
                if lender is not None:
                    x["is_financial"] = lender
                x["ebitda"] = _ebitda(x)
                card = _card_from_lines(x, mult, "results filing")
                card.update({"periods": x.get("periods"), "basis": x.get("basis"), "unit": "₹ Cr",
                             "page": x.get("page"), "is_financial": x.get("is_financial"),
                             "source_url": item.get("url"),
                             "verification": "Extracted values occur on the cited page; row and column interpretation still requires review.",
                             "calculation": "EBITDA = PBT + finance costs + depreciation - other income - exceptional items. QoQ and YoY use the labeled comparison quarters."})
                if x.get("is_financial"):
                    card["note"] = "Lender: EBITDA is not meaningful; read revenue as total income."
            except (llm.LLMUnavailable, AttributeError, TypeError, ValueError):
                card = None
    # cross-check against screener (or fall back to it)
    sc_card = screener_card(sc) if sc else None
    if card and sc_card:
        same_period = bool(_norm_periods(card.get("periods"))) and _norm_periods(card.get("periods")) == _norm_periods(sc_card.get("periods"))
        same_basis = card.get("basis") == sc_card.get("basis")
        if same_period and same_basis:
            a, b = card["metrics"][0]["cur"], sc_card["metrics"][0]["cur"]
            if a is not None and b:
                diff = abs(a / b - 1)
                card["check"] = {"ok": diff < 0.03, "vs": "screener revenue only", "diff_pct": round(diff * 100, 1)}
        else:
            card["note"] = (card.get("note", "") + " Cross-check unavailable: period or reporting basis differs.").strip()
    if not card or card["metrics"][0]["cur"] is None:
        return {"error": "Could not verify this filing's numbers. Open the original filing; latest-quarter figures have not been substituted."}
    if card.get("is_financial"):
        for metric in card["metrics"]:
            if metric["key"] == "ebitda":
                for field in ("cur", "prev", "yago", "qoq", "yoy", "margin", "margin_yago"):
                    metric[field] = None
    if card:
        card["verdict"] = _verdict(card)
        db.kv_set("card_results", key, card)
    return card or {"error": "Could not read numbers from this filing."}


def _verdict(card: dict) -> str:
    """Deterministic one-liner. No model needed to say 'revenue up, margins down'."""
    m = {x["key"]: x for x in card["metrics"]}
    bits = []
    r, p = m["revenue"], m["pat"]
    if r.get("yoy") is not None:
        bits.append(f"Revenue {r['yoy']:+.0f}% YoY")
    e = m["ebitda"]
    if e.get("margin") is not None and e.get("margin_yago") is not None:
        d = e["margin"] - e["margin_yago"]
        bits.append(f"EBITDA margin {e['margin']:.1f}% ({d:+.1f}pp YoY)")
    if p.get("yoy") is not None:
        bits.append(f"PAT {p['yoy']:+.0f}% YoY")
    if r.get("yoy") is not None and p.get("yoy") is not None:
        if p["yoy"] > r["yoy"] + 5:
            bits.append("PAT growing faster than revenue; cause not verified")
        elif p["yoy"] < r["yoy"] - 5:
            bits.append("profit lagging sales")
    return " · ".join(bits)


MGMT_PROMPT = """Below is an Indian listed company's disclosure about a change in directors / key managerial personnel.
Extract every change. Use only the text. Return JSON:
{{"changes":[{{"person":"","role":"","action":"appointed|resigned|retired|redesignated|ceased",
  "effective":"date or null","reason":"short or null",
  "profile":"2 sentence background exactly as disclosed (education, prior roles, years), or null",
  "prior_roles":["Org — Role", ...]}}]}}

TEXT:
{text}"""


async def mgmt_card(item: dict) -> dict:
    hit = db.kv_get("card_mgmt", item["id"])
    if hit:
        return hit[0]
    pgs = await pdftext.pages(item.get("url", ""), max_pages=8)
    text = "\n".join(pgs)[:12000] or f"{item['headline']}. {item['text']}"
    try:
        x = await llm.call("mgmt_extract", MGMT_PROMPT.format(text=text), tier="cheap")
        changes = x.get("changes", [])
    except (llm.LLMUnavailable, AttributeError):
        changes = []
    for c in changes:
        q = f"{c.get('person', '')} {item.get('company') or item['symbol']}"
        c["linkedin"] = f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(q)}"
        if config.TAVILY_API_KEY and c.get("action") == "appointed" and c.get("person"):
            c["web"] = await _web_bio(c["person"], item.get("company") or item["symbol"])
    card = {"changes": changes}
    db.kv_set("card_mgmt", item["id"], card)
    return card


async def _web_bio(person: str, company: str) -> dict | None:
    """Push-side enrichment (allowed by the brief): professional background from the open web."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": config.TAVILY_API_KEY, "query": f"{person} {company} LinkedIn career background",
                "max_results": 5, "include_answer": False})
            res = r.json().get("results", [])
        snippets = "\n".join(f"- {x['title']}: {x['content'][:400]} ({x['url']})" for x in res)
        out = await llm.call("bio_summarise",
                             f"Summarise the professional background of {person} (joining {company}) in max 2 "
                             f"sentences: prior employers, roles, years. Only use these snippets; if they look like a "
                             f"different person, return null.\n{snippets}\nReturn JSON {{\"bio\": str|null, \"urls\": [str]}}",
                             tier="cheap")
        return out if out.get("bio") else None
    except Exception:
        return None


ONELINER_PROMPT = """You brief a busy portfolio manager. In ONE line (max 22 words), say what this filing means: the
fact plus the number that matters (amount, %, counterparty, date). No preamble, no adjectives, no advice.
Company: {company}. Exchange subject: {head}.
FILING TEXT:
{text}
Return JSON {{"line": "..."}}"""

BOILER = re.compile(r"^(?:[\w&.,():'-]+ )*?has (?:informed|submitted to) the exchange (?:about|regarding|that)?\s*", re.I)


def exchange_line(item: dict) -> str:
    """Free one-liner: the exchange's own summary, de-boilerplated."""
    t = BOILER.sub("", item.get("text", "")).strip()
    t = re.sub(r"\s+", " ", t)
    return (t[:1].upper() + t[1:])[:220] if t else ""


async def ai_line(item: dict) -> str:
    hit = db.kv_get("card_line", item["id"])
    if hit:
        return hit[0]
    pgs = await pdftext.pages(item.get("url", ""), max_pages=3)
    text = "\n".join(pgs)[:6000]
    if len(text) < 200:
        return exchange_line(item)
    try:
        out = await llm.call("one_liner", ONELINER_PROMPT.format(company=item.get("company") or item["symbol"],
                                                                 head=item["headline"], text=text), tier="cheap")
        line = (out.get("line") or "").strip()
    except (llm.LLMUnavailable, AttributeError):
        line = ""
    line = line or exchange_line(item)
    db.kv_set("card_line", item["id"], line)
    return line


async def enrich(item: dict) -> dict:
    cat, sub = item.get("category"), item.get("subtype")
    out: dict = {"id": item["id"]}
    if cat == "results" and sub != "intimation":
        out["results"] = await results_card(item)
    elif cat == "management_change":
        out["mgmt"] = await mgmt_card(item)
    else:
        out["line"] = await ai_line(item)
    return out
