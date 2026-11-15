"""End-of-day price & volume from Yahoo Finance's chart endpoint (the same data yfinance wraps, minus pandas)."""
from __future__ import annotations

import asyncio
import logging
import json
import math
from datetime import datetime, timezone, timedelta

from .. import config, db
from . import refresh

IST = timezone(timedelta(hours=5, minutes=30))
TTL = 30 * 60


async def history(symbol: str, exchange: str = "NS", *, allow_background: bool = True) -> dict | None:
    """1y daily OHLCV. Cached 30 min; falls back to stale cache (or seed) if Yahoo is unreachable."""
    key = f"{symbol}.{exchange}"
    if config.FIXTURES:
        p = config.FIXTURE_DIR / "prices" / f"{symbol}.json"
        return json.loads(p.read_text()) if p.exists() else None
    hit = db.kv_get("prices", key, TTL)
    if hit:
        return hit[0]
    stale = db.kv_get_stale("prices", key)
    if config.FAST_FEEDS and allow_background:
        refresh.schedule(f"prices:{key}", lambda: history(symbol, exchange, allow_background=False))
        return {**stale[0], "stale": True} if stale else None
    try:
        async with _download_lock:
            data = await asyncio.to_thread(_download, symbol, key)
        if data["rows"]:
            db.kv_set("prices", key, data)
            return data
    except Exception as exc:
        logging.getLogger(__name__).warning("Price fetch failed for %s: %s", key, type(exc).__name__)
    return {**stale[0], "stale": True} if stale else None


_download_lock = asyncio.Lock()


def _download(symbol: str, key: str) -> dict:
    import yfinance as yf
    yf.set_tz_cache_location(str(config.DATA_DIR / "yfinance"))
    frame = yf.Ticker(key).history(period="1y", interval="1d", auto_adjust=False, timeout=20)
    rows = []
    for stamp, row in frame.iterrows():
        if not all(math.isfinite(float(row[k])) for k in ("Open", "High", "Low", "Close", "Volume")):
            continue
        rows.append({"d": stamp.strftime("%Y-%m-%d"), "o": float(row["Open"]),
                     "h": float(row["High"]), "l": float(row["Low"]),
                     "c": float(row["Close"]), "v": int(row["Volume"])})
    return {"symbol": symbol, "name": symbol, "currency": "INR", "rows": rows}


def eod_stats(h: dict | None, lookback: int = 20) -> dict | None:
    """Turn raw history into the numbers the alert engine and UI need."""
    if not h or len(h.get("rows", [])) < 3:
        return None
    rows = h["rows"]
    # Conservative publication buffer; do not treat a live daily bar as final.
    now = datetime.now(IST)
    rows = [r for r in rows if r["d"] < now.strftime("%Y-%m-%d") or
            (r["d"] == now.strftime("%Y-%m-%d") and now.hour >= 17)]
    if len(rows) < 3:
        return None
    last, prev = rows[-1], rows[-2]
    window = rows[-(lookback + 1):-1]
    avg_vol = sum(r["v"] for r in window) / max(len(window), 1)
    closes = [r["c"] for r in rows]
    chg = (last["c"] / prev["c"] - 1) * 100 if prev["c"] else 0.0
    # realised daily vol (for "how unusual is this move" context)
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - 60), len(closes)) if closes[i - 1]]
    sd = (sum((x - sum(rets) / len(rets)) ** 2 for x in rets) / max(len(rets) - 1, 1)) ** 0.5 * 100 if rets else 0
    return {
        "symbol": h["symbol"], "name": h.get("name"), "date": last["d"], "close": round(last["c"], 2),
        "chg_pct": round(chg, 2), "volume": last["v"], "avg_volume": round(avg_vol),
        "vol_mult": round(last["v"] / avg_vol, 2) if avg_vol else None,
        "sigma": round(abs(chg) / sd, 1) if sd else None,
        "hi52": round(max(closes), 2), "lo52": round(min(closes), 2),
        "spark": [round(c, 2) for c in closes[-30:]], "stale": bool(h.get("stale")),
    }
