"""Corporate announcements. NSE JSON API first, BSE API as fallback (NSE often blocks datacenter IPs)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx

from .. import config, db
from ..http import client, nse_client

IST = timezone(timedelta(hours=5, minutes=30))
TTL = 10 * 60


def _norm_nse(r: dict) -> dict:
    ts = None
    for fmt, field in (("%d-%b-%Y %H:%M:%S", "an_dt"), ("%Y-%m-%d %H:%M:%S", "sort_date"), ("%d%m%Y%H%M%S", "dt")):
        try:
            ts = datetime.strptime(r.get(field) or "", fmt).replace(tzinfo=IST)
            break
        except ValueError:
            continue
    return {
        "id": f"nse:{r.get('seq_id') or r.get('dt')}:{r.get('symbol')}",
        "symbol": r.get("symbol"), "company": r.get("sm_name"),
        "ts": (ts or datetime.now(IST)).isoformat(),
        "headline": (r.get("desc") or "").strip(),
        "text": (r.get("attchmntText") or "").strip(),
        "url": r.get("attchmntFile") or "", "source": "NSE",
    }


def _norm_bse(r: dict, symbol: str) -> dict:
    try:
        ts = datetime.fromisoformat((r.get("NEWS_DT") or r.get("DT_TM") or "")[:19]).replace(tzinfo=IST)
    except ValueError:
        ts = datetime.now(IST)
    att = r.get("ATTACHMENTNAME") or ""
    return {
        "id": f"bse:{r.get('NEWSID')}", "symbol": symbol, "company": r.get("SLONGNAME"),
        "ts": ts.isoformat(),
        "headline": " - ".join(x for x in [r.get("CATEGORYNAME"), r.get("SUBCATNAME")] if x and x != "-") or "Update",
        "text": (r.get("HEADLINE") or r.get("NEWSSUB") or "").strip(),
        "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
        "source": "BSE",
    }


async def _nse(symbol: str, start: datetime, end: datetime) -> list[dict]:
    c = await nse_client()
    r = await c.get("https://www.nseindia.com/api/corporate-announcements", params={
        "index": "equities", "symbol": symbol,
        "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    return [_norm_nse(x) for x in rows]


async def _bse(symbol: str, scrip: str, start: datetime, end: datetime) -> list[dict]:
    r = await client().get(
        "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        params={"pageno": 1, "strCat": -1, "strPrevDate": start.strftime("%Y%m%d"), "strScrip": scrip,
                "strSearch": "P", "strToDate": end.strftime("%Y%m%d"), "strType": "C", "subcategory": -1},
        headers={"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})
    r.raise_for_status()
    return [_norm_bse(x, symbol) for x in r.json().get("Table", [])]


async def for_symbol(symbol: str, bse_code: str | None, hours: int) -> tuple[list[dict], str]:
    """Returns (announcements, status) where status is live|cache|stale|error."""
    end = datetime.now(IST)
    start = end - timedelta(hours=hours)
    if config.FIXTURES:
        p = config.FIXTURE_DIR / "announcements.json"
        rows = [x for x in json.loads(p.read_text()) if x["symbol"] == symbol]
        return rows, "fixture"
    # cache by day-granular window so 24h/48h requests share fetches
    days = max(1, (hours + 23) // 24)
    key = f"{symbol}:{days}"
    hit = db.kv_get("ann", key, TTL)
    if hit:
        return _window(hit[0], start), "cache"
    rows: list[dict] | None = None
    try:
        rows = await _nse(symbol, end - timedelta(days=days), end)
    except (httpx.HTTPError, ValueError):
        if bse_code:
            try:
                rows = await _bse(symbol, bse_code, end - timedelta(days=days), end)
            except (httpx.HTTPError, ValueError):
                rows = None
    if rows is None:
        stale = db.kv_get_stale("ann", key)
        if not stale:
            return [], "error"
        # feed down: show the same window as of when we last saw the feed, not as of now
        return _window(stale[0], start), "stale"
    db.kv_set("ann", key, rows)
    return _window(rows, start), "live"


def _window(rows: list[dict], start: datetime) -> list[dict]:
    return [r for r in rows if datetime.fromisoformat(r["ts"]) >= start] if not config.FIXTURES else rows


async def for_portfolio(holdings: list[dict], hours: int) -> tuple[list[dict], dict]:
    sem = asyncio.Semaphore(4)

    async def one(hd):
        async with sem:
            return hd["symbol"], await for_symbol(hd["symbol"], hd.get("bse"), hours)

    results = await asyncio.gather(*(one(h) for h in holdings))
    rows, status = [], {}
    for sym, (r, st) in results:
        rows.extend(r)
        status[sym] = st
    # de-dup (same filing can surface twice via NSE+BSE)
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: x["ts"], reverse=True):
        k = (r["symbol"], r["headline"][:40], r["ts"][:16])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out, status
