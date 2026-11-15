"""Priority = what earns the investor's attention. Transparent, additive, and every point has a reason the UI can show."""
from __future__ import annotations

import re

BASE = {
    "results": 80, "M&A": 74, "management_change": 66, "fund_raise": 70, "credit_rating": 52, "litigation": 58,
    "pledging": 64, "capex": 58, "insider_trading": 44, "bonus_split": 52, "dividend": 38, "press_release": 38,
    "earnings_call": 30, "investor_meetings": 18, "agm_egm": 22, "postal_ballot": 24, "unclassified": 4,
}

# Policy: what each tier gets. Act = rich card + AI one-liner. Know = exchange's own one-liner. Routine = collapsed.
TIERS = [(65, "act"), (40, "know"), (0, "routine")]

SIZE_SENSITIVE = {"press_release", "capex", "M&A", "fund_raise", "litigation"}
AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|lakh|million|mn|billion|bn)", re.I)


def amount_cr(text: str) -> float | None:
    m = AMOUNT.search(text or "")
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return v * {"crore": 1, "cr": 1, "lakh": 0.01, "million": 0.1, "mn": 0.1, "billion": 100, "bn": 100}[unit]


def score(item: dict, holding: dict | None, eod: dict | None, bias: dict) -> dict:
    cat, sub = item.get("category", "unclassified"), item.get("subtype", "")
    text = f"{item.get('headline', '')} {item.get('text', '')}"
    s = BASE.get(cat, 10)
    why = [f"{cat.replace('_', ' ')}"]
    if cat == "results" and sub == "intimation":
        s, why = 30, ["results date announced"]
    if cat == "management_change":
        if re.search(r"\b(ceo|managing director|chief executive|cfo|chief financial)\b", text, re.I):
            s += 14
            why.append("CEO/CFO/MD level")
        elif re.search(r"independent director", text, re.I):
            s -= 22
            why.append("independent director only")
        if re.search(r"resign", text, re.I):
            s += 6
            why.append("resignation")
    if cat == "credit_rating":
        if re.search(r"downgrad|negative|watch with negative", text, re.I):
            s += 26
            why.append("downgrade / negative outlook")
        elif re.search(r"upgrad|positive", text, re.I):
            s += 12
            why.append("upgrade")
        elif re.search(r"reaffirm", text, re.I):
            s -= 18
            why.append("reaffirmed")
    if cat == "litigation" and re.search(r"warning letter|import alert|insolvency|nclt|search and seizure|sebi order", text, re.I):
        s += 12
        why.append("regulatory action")
    if cat == "earnings_call" and re.search(r"transcript", text, re.I):
        s += 12
        why.append("transcript out")
    if cat == "insider_trading" and re.search(r"promoter", text, re.I) and re.search(r"sale|sold|dispos", text, re.I):
        s += 18
        why.append("promoter selling")
    if cat == "press_release" and sub == "order":
        s += 14
        why.append("order win")
    amt = amount_cr(text)
    if amt and cat in SIZE_SENSITIVE:
        s += 6
        why.append(f"₹{amt:,.0f} Cr")
    band = (holding or {}).get("band")
    if cat in SIZE_SENSITIVE and band in ("Mid", "Small"):
        s += 4 if band == "Mid" else 8
        why.append(f"{band.lower()}-cap: more material")
    if eod and abs(eod.get("chg_pct") or 0) >= 3 and cat != "unclassified":
        s += 8
        why.append(f"stock {eod['chg_pct']:+.1f}% today")
    b = bias.get(cat, 0)
    if b:
        s += b
        why.append("you " + ("care about" if b > 0 else "usually skip") + " these")
    s = max(0, min(100, s))
    tier = next(t for th, t in TIERS if s >= th)
    return {"score": s, "tier": tier, "why": why}
