"""Triggered alerts: (1) a material filing of a type you care about, (2) an unusual EOD move by YOUR definition.
New alerts are stored (deduped) and optionally pushed to Telegram — a real push to a phone with zero app install."""
from __future__ import annotations

import json
import time

import httpx

from .. import config, db
from . import digest, enrich


LABEL = {"results": "results", "M&A": "deal", "fund_raise": "fund-raise", "management_change": "management change",
         "litigation": "legal or regulatory", "credit_rating": "credit rating", "pledging": "pledge change",
         "capex": "capex", "insider_trading": "insider trade", "bonus_split": "bonus or split", "dividend": "dividend",
         "press_release": "company update"}


def eod_rules(stats: dict, s: dict) -> list[dict]:
    out = []
    vm, chg = stats.get("vol_mult"), stats.get("chg_pct") or 0
    ctx = []
    if stats["close"] >= stats["hi52"] * 0.999:
        ctx.append("at a 52-week high")
    elif stats["close"] <= stats["lo52"] * 1.001:
        ctx.append("at a 52-week low")
    if stats.get("sigma"):
        ctx.append(f"a {stats['sigma']:.1f}σ day")
    if vm and vm >= s["volume_multiple"]:
        out.append({"kind": "volume", "title": f"{stats['symbol']} volume {vm:.1f}× normal",
                    "why": f"{stats['volume']:,} shares vs {s['volume_lookback']}-day avg {stats['avg_volume']:,} "
                           f"(your trigger: {s['volume_multiple']}×). Price {chg:+.1f}%"
                           + (f", {', '.join(ctx)}" if ctx else "") + "."})
    if abs(chg) >= s["price_move_pct"]:
        out.append({"kind": "price", "title": f"{stats['symbol']} {'+' if chg > 0 else ''}{chg:.1f}% today",
                    "why": f"Closed ₹{stats['close']:,} (your trigger: ±{s['price_move_pct']}%)"
                           + (f", {', '.join(ctx)}" if ctx else "") + "."})
    for a in out:
        a.update({"id": f"eod:{stats['symbol']}:{stats['date']}:{a['kind']}", "symbol": stats["symbol"],
                  "payload": {"eod": stats}})
    return out


async def scan(push: bool = True) -> dict:
    s = db.get_settings()
    d = await digest.build(24)
    candidates: list[dict] = []
    for it in d["items"]:
        if it["category"] in s["alert_categories"] and it["score"] >= s["min_alert_priority"]:
            candidates.append({"id": f"filing:{it['id']}", "kind": "filing", "symbol": it["symbol"],
                               "title": f"{it['symbol']}: {LABEL.get(it['category'], it['category'])}",
                               "why": it.get("line") or it["headline"], "payload": {"item_id": it["id"],
                                                                                     "url": it.get("url")}})
    for st in d["tape"]:
        if not st.get("stale"):
            candidates.extend(eod_rules(st, s))
    scope = db.reviewer.get()
    if scope:
        for candidate in candidates:
            candidate["id"] = f"reviewer:{scope}:{candidate['id']}"
    existing = {r[0] for r in db.execute("SELECT id FROM alerts")}
    new = [c for c in candidates if c["id"] not in existing]
    for a in new:
        if a["kind"] == "filing":   # enrich before pushing so the phone notification is self-contained
            it = (db.kv_get_stale("item", a["payload"]["item_id"]) or ({}, 0))[0]
            try:
                e = await enrich.enrich(it)
                if e.get("results") and e["results"].get("verdict"):
                    a["why"] = e["results"]["verdict"]
                elif e.get("line"):
                    a["why"] = e["line"]
                elif e.get("mgmt", {}).get("changes"):
                    c = e["mgmt"]["changes"][0]
                    a["why"] = f"{c.get('person')} {c.get('action')} as {c.get('role')}. {c.get('profile') or ''}".strip()
            except Exception:
                pass
        db.execute("INSERT OR IGNORE INTO alerts VALUES (?,?,?,?,?,?,?,0)",
                   (a["id"], a["kind"], a["symbol"], a["title"], a["why"], json.dumps(a["payload"]), time.time()))
    sent = 0
    if push and not scope and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        pending = db.execute("SELECT id, title, why, payload FROM alerts WHERE sent=0 AND id NOT LIKE 'reviewer:%' ORDER BY ts LIMIT 60")
        for aid, title, why, payload in pending:
            a = {"id": aid, "title": title, "why": why, "payload": json.loads(payload)}
            if await telegram(a):
                db.execute("UPDATE alerts SET sent=1 WHERE id=?", (a["id"],))
                sent += 1
    return {"new": len(new), "pushed": sent, "checked": len(candidates)}


def recent(limit: int = 60) -> list[dict]:
    scope = db.reviewer.get()
    rows = db.execute("SELECT id, kind, symbol, title, why, payload, ts, sent FROM alerts "
                      "WHERE id NOT LIKE 'reviewer:%' OR id LIKE ? ORDER BY ts DESC LIMIT ?",
                      (f"reviewer:{scope}:%" if scope else "", limit))
    return [{"id": r[0], "kind": r[1], "symbol": r[2], "title": r[3], "why": r[4], "payload": json.loads(r[5]),
             "ts": r[6], "sent": bool(r[7])} for r in rows]


async def telegram(a: dict) -> bool:
    url = (a.get("payload") or {}).get("url")
    text = f"*{a['title']}*\n{a['why']}" + (f"\n[Filing]({url})" if url else "")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                             json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown",
                                   "disable_web_page_preview": True})
        return r.status_code == 200
    except httpx.HTTPError:
        return False
