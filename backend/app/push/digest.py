"""The windowed digest: every filing across the portfolio, classified, scored, tiered."""
from __future__ import annotations

import asyncio
from collections import Counter

from .. import config, db
from ..sources import announcements, prices
from . import classify, enrich, score


def holdings() -> list[dict]:
    p = config.load_portfolio()
    s = db.get_settings()
    out = [h for h in p["portfolio"] if h["symbol"] not in s["removed_symbols"]]
    out += [{"symbol": x, "name": x, "sector": "", "band": "Mid"} for x in s["extra_symbols"]
            if x not in {h["symbol"] for h in out}]
    return out


async def tape(lookback: int = 20) -> dict[str, dict]:
    hs = holdings()
    sem = asyncio.Semaphore(6)

    async def one(h):
        async with sem:
            return h["symbol"], prices.eod_stats(await prices.history(h["symbol"]), lookback)

    return {k: v for k, v in await asyncio.gather(*(one(h) for h in hs)) if v}


async def build(hours: int) -> dict:
    s = db.get_settings()
    hs = holdings()
    by_sym = {h["symbol"]: h for h in hs}
    (items, status), eod = await asyncio.gather(announcements.for_portfolio(hs, hours), tape(s["volume_lookback"]))
    try:
        await asyncio.wait_for(classify.classify_all(items), timeout=4)
    except TimeoutError:
        for item in items:
            if "category" not in item:
                item.update(category="unclassified", subtype="unknown", classified_by="fallback")
    scope = db.reviewer.get()
    if scope:
        triage = (db.kv_get("reviewer_triage", scope) or ({}, 0))[0]
    else:
        triage = dict(db.execute("SELECT item_id, state FROM triage"))
    for it in items:
        it.update(score.score(it, by_sym.get(it["symbol"]), eod.get(it["symbol"]), s["category_bias"]))
        it["state"] = triage.get(it["id"], "new")
        if it["tier"] == "know":
            it["line"] = enrich.exchange_line(it)
        it["name"] = (by_sym.get(it["symbol"]) or {}).get("name") or it.get("company")
        db.kv_set("item", it["id"], it)
    items.sort(key=lambda x: (x["score"], x["ts"]), reverse=True)
    tiers = Counter(i["tier"] for i in items)
    routine_by_cat = Counter(i["category"] for i in items if i["tier"] == "routine")
    movers = sorted((v for v in eod.values() if v.get("vol_mult") and
                     (v["vol_mult"] >= s["volume_multiple"] or abs(v["chg_pct"]) >= s["price_move_pct"])),
                    key=lambda v: -max(v["vol_mult"] / s["volume_multiple"], abs(v["chg_pct"]) / s["price_move_pct"]))
    return {
        "hours": hours, "items": items, "counts": dict(tiers), "routine_by_category": dict(routine_by_cat),
        "headline": headline(items, movers), "tape": [eod[h["symbol"]] for h in hs if h["symbol"] in eod],
        "movers": [m["symbol"] for m in movers], "feed_status": status,
        "fixtures": config.FIXTURES,
    }


def headline(items: list[dict], movers: list[dict]) -> str:
    """Deterministic one-sentence brief. Template beats a model here: it never hallucinates a count."""
    act = [i for i in items if i["tier"] == "act" and i.get("state", "new") not in ("done", "less")]
    if not act and not movers:
        hidden = sum(1 for i in items if i["tier"] == "routine")
        return f"Quiet window. Nothing needs you" + (f" — {hidden} routine filings tucked away." if hidden else ".")
    c = Counter(i["category"] for i in act)
    names = {"results": "result", "management_change": "management change", "M&A": "deal", "fund_raise": "fund-raise",
             "credit_rating": "rating action", "litigation": "legal matter", "pledging": "pledge change",
             "capex": "capex plan", "press_release": "update", "insider_trading": "insider trade",
             "bonus_split": "bonus/split", "dividend": "dividend", "earnings_call": "call"}
    parts = []
    for k, n in c.most_common(6):
        w = names.get(k, k.replace("_", " "))
        parts.append(f"{n} {w}{'s' if n > 1 and not w.endswith('s') else ''}")
    if movers:
        parts.append(f"{len(movers)} unusual move{'s' if len(movers) > 1 else ''} ({', '.join(m['symbol'] for m in movers[:2])})")
    return f"{len(act) + len(movers)} things need you: " + ", ".join(parts) + "."


def triage(item_id: str, state: str) -> dict:
    """done | keep | less. 'less' teaches the ranker to push this category down for you."""
    hit = db.kv_get_stale("item", item_id)
    it = hit[0] if hit else {}
    scope = db.reviewer.get()
    if scope:
        states = (db.kv_get("reviewer_triage", scope) or ({}, 0))[0]
        states[item_id] = state
        db.kv_set("reviewer_triage", scope, states)
    else:
        db.execute("INSERT OR REPLACE INTO triage VALUES (?,?,?,?,strftime('%s','now'))",
                   (item_id, state, it.get("symbol"), it.get("category")))
    s = db.get_settings()
    cat = it.get("category")
    if cat and state in ("less", "more"):
        bias = dict(s["category_bias"])
        bias[cat] = max(-30, min(20, bias.get(cat, 0) + (-8 if state == "less" else 6)))
        db.save_settings({"category_bias": bias})
    return {"ok": True, "category_bias": db.get_settings()["category_bias"]}
