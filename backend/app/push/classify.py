"""Announcement -> category. Rules first (free, instant, explainable); cheap LLM only for leftovers, batched.

On a typical day ~80-90% of filings resolve from the exchange's own subject line + a few keywords.
"""
from __future__ import annotations

import json
import re

from .. import db, llm

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]

I = re.I
# (category, subtype, headline regex, text regex or None). First match wins. Order matters.
RULES: list[tuple[str, str, re.Pattern, re.Pattern | None]] = [
    ("unclassified", "newspaper", re.compile(r"newspaper|publication", I), None),
    ("unclassified", "routine", re.compile(r"trading window|depositories and participants|loss of share|duplicate share"
                                           r"|investor complaints|compliance certificate|esop|esos|esps|sustainability"
                                           r"|share certificate|74\s*\(5\)|record of transfer|cyber", I), None),
    ("results", "intimation", re.compile(r"board meeting intimation|prior intimation", I),
     re.compile(r"financial results?|quarter|half year|audited|unaudited", I)),
    ("results", "filing", re.compile(r"financial result|integrated filing.*financ", I), None),
    ("management_change", "kmp", re.compile(r"change in (directors|management)|key managerial|resignation|cessation|appointment", I),
     re.compile(r"\b(ceo|cfo|chief|managing director|\bmd\b|whole[- ]time director|director|president|chairman|chairperson|head)\b", I)),
    ("unclassified", "auditor_cs", re.compile(r"change in directors|key managerial|compliance officer|auditor", I), None),
    ("earnings_call", "call", re.compile(r"analysts?/institutional|con\. ?call|conference call|earnings call", I),
     re.compile(r"conference call|earnings call|con\.? ?call|transcript|audio|recording|webcast|results call", I)),
    ("investor_meetings", "meet", re.compile(r"analysts?/institutional|investor meet|investor conference", I), None),
    ("credit_rating", "rating", re.compile(r"credit rating", I), None),
    ("M&A", "deal", re.compile(r"acquisition|amalgamation|merger|demerger|scheme of arrangement|joint venture"
                              r"|sale or disposal|disinvestment|divestment|incorporation of.*subsidiary|investment in", I), None),
    ("fund_raise", "raise", re.compile(r"qualified institutional|\bqip\b|preferential|rights issue|buy ?back|commercial paper"
                                      r"|non[- ]convertible|debenture|raising of funds|fund rais|issue of securities", I), None),
    ("bonus_split", "action", re.compile(r"bonus|sub-?division|stock split|split of", I), None),
    ("dividend", "cash", re.compile(r"dividend", I), None),
    ("pledging", "pledge", re.compile(r"pledge|encumbrance", I), None),
    ("insider_trading", "pit", re.compile(r"insider trading|\bpit\b|takeover regulations|sast|acquisition of shares by promoter", I), None),
    ("litigation", "legal", re.compile(r"litigation|dispute|penalt|show cause|regulatory action|order passed|tax demand|insolvency"
                                      r"|nclt|cirp|sebi order|fine\b|warning letter|import alert", I), None),
    ("capex", "capacity", re.compile(r"capacity|commercial production|new plant|expansion|capital expenditure|capex", I), None),
    ("postal_ballot", "ballot", re.compile(r"postal ballot", I), None),
    ("agm_egm", "meeting", re.compile(r"general meeting|\bagm\b|\begm\b|shareholders meeting", I), None),
    ("press_release", "order", re.compile(r"bagging|receipt of order|award of|order win|orders? received|contract", I), None),
    ("press_release", "clarification", re.compile(r"clarification|spurt in volume|price movement", I), None),
    ("press_release", "release", re.compile(r"press release|media release", I), None),
]

# For generic subject lines ("Updates", "Outcome of Board Meeting", "Disclosure under Reg 30") look inside the text.
TEXT_RULES: list[tuple[str, str, re.Pattern]] = [
    ("results", "filing", re.compile(r"(un)?audited (standalone|consolidated)? ?financial results|financial results for the (quarter|half|year)", I)),
    ("management_change", "kmp", re.compile(r"(appoint|resign|cessation|re-?designat)\w* .{0,60}(ceo|cfo|chief|managing director|director)", I)),
    ("M&A", "deal", re.compile(r"acqui(re|sition)|amalgamation|merger|demerger|joint venture|stake sale|divest", I)),
    ("fund_raise", "raise", re.compile(r"qualified institutional|preferential (issue|allotment)|rights issue|buy-?back|non-convertible|commercial paper", I)),
    ("credit_rating", "rating", re.compile(r"\b(crisil|icra|care ratings|india ratings|brickwork|acuite)\b.*rating|rating.*(reaffirm|upgrade|downgrade)", I)),
    ("dividend", "cash", re.compile(r"(interim|final|special) dividend", I)),
    ("bonus_split", "action", re.compile(r"bonus (issue|shares)|sub-?division|stock split", I)),
    ("capex", "capacity", re.compile(r"capacity expansion|greenfield|brownfield|new (plant|facility|unit)|commercial production", I)),
    ("press_release", "order", re.compile(r"(order|contract)s? (worth|valued|of|aggregating)|letter of (award|intent)|bagged", I)),
    ("litigation", "legal", re.compile(r"penalty|show cause|demand order|tax demand|nclt|tribunal|court|warning letter"
                                      r"|import alert|form 483|observations? from (usfda|regulator)|search and seizure", I)),
    ("insider_trading", "pit", re.compile(r"promoter.{0,40}(sale|sold|dispos|purchase|acqui)|insider trading", I)),
    ("earnings_call", "call", re.compile(r"transcript|audio recording|conference call|earnings call", I)),
    ("investor_meetings", "meet", re.compile(r"investor meet|analyst meet|one-on-one|non-deal roadshow", I)),
    ("pledging", "pledge", re.compile(r"pledge|encumbrance", I)),
]


SENIOR = re.compile(r"\b(ceo|cfo|coo|cto|chief|managing director|whole[- ]time director|executive director|chairman"
                    r"|chairperson|president)\b", I)
SECRETARIAL = re.compile(r"company secretary|compliance officer|auditor|registrar|share transfer agent", I)


def _only_secretarial(text: str) -> bool:
    return bool(SECRETARIAL.search(text)) and not SENIOR.search(text)


def rule_classify(item: dict) -> tuple[str, str] | None:
    head, text = item.get("headline", ""), item.get("text", "")
    both = f"{head} {text}"
    if re.search(r"redemption|repayment", both, I) and re.search(r"commercial paper|debenture|debt", both, I):
        return "press_release", "debt_repayment"
    generic = re.search(r"^(general )?updates?$|outcome of board meeting|disclosure under (sebi \(listing|regulation 30)"
                        r"|^regulation 30|^announcement|^press release|^media release", head, I)
    if generic:   # vague subject line: the text decides; fall back to subject-line rules after
        for cat, sub, tre in TEXT_RULES:
            if tre.search(both):
                return cat, sub
    for cat, sub, hre, tre in RULES:
        if hre.search(head) and (tre is None or tre.search(text or head)):
            if cat == "management_change" and _only_secretarial(text):
                return "unclassified", "auditor_cs"
            return cat, sub
    if not generic:
        for cat, sub, tre in TEXT_RULES:
            if tre.search(both):
                return cat, sub
    return None   # e.g. "Outcome of Board Meeting" with no telling keywords -> ask the model


async def classify_all(items: list[dict]) -> None:
    """Mutates items in place with category/subtype/classified_by."""
    pending = []
    n_rules = 0
    for it in items:
        cached = db.kv_get("cls_v2", it["id"])
        if cached:
            it.update(cached[0])
            continue
        r = rule_classify(it)
        if r:
            it.update({"category": r[0], "subtype": r[1], "classified_by": "rules"})
            n_rules += 1
            db.kv_set("cls_v2", it["id"], {k: it[k] for k in ("category", "subtype", "classified_by")})
        else:
            pending.append(it)
    n_llm = 0
    for i in range(0, len(pending), 25):
        batch = pending[i:i + 25]
        payload = [{"id": it["id"], "subject": it["headline"], "text": it["text"][:400]} for it in batch]
        prompt = (
            "Classify each Indian listed-company exchange filing into exactly one category.\n"
            f"Categories: {', '.join(CATEGORIES)}.\n"
            "Guide: results=quarterly/annual results or their board approval; M&A=acquisition/merger/JV/subsidiary "
            "investment or stake sale; fund_raise=QIP/rights/preferential/buyback/debt; management_change=CEO/CFO/MD/"
            "director joins or leaves; unclassified=routine paperwork that does not move the stock.\n"
            'Return JSON: {"labels": {"<id>": "<category>", ...}}\n\n' + json.dumps(payload, ensure_ascii=False))
        try:
            out = await llm.call("classify", prompt, tier="cheap")
            labels = out.get("labels", {}) if isinstance(out, dict) else {}
        except llm.LLMUnavailable:
            labels = {}
        for it in batch:
            cat = labels.get(it["id"])
            if cat in CATEGORIES:
                it.update({"category": cat, "subtype": "llm", "classified_by": "llm"})
                n_llm += 1
                db.kv_set("cls_v2", it["id"], {k: it[k] for k in ("category", "subtype", "classified_by")})
            else:
                it.update({"category": "unclassified", "subtype": "unknown", "classified_by": "fallback"})
    stats = (db.kv_get_stale("stats", "classifier") or ({"rules": 0, "llm": 0}, 0))[0]
    stats["rules"] += n_rules
    stats["llm"] += n_llm
    db.kv_set("stats", "classifier", stats)
