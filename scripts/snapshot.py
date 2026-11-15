"""Run once on a machine that can reach NSE/BSE/Yahoo/screener (an Indian home connection is ideal).

  python scripts/snapshot.py --check      # 30-second smoke test of every live source + the LLM key
  python scripts/snapshot.py              # warm everything and write data/seed.jsonl.gz

Warms the local cache and exports source data plus results cards. The seed excludes reviewer
settings, Q&A and model caches. Live feeds still take priority and stale data is labeled.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config, db, llm  # noqa: E402
from app.pull import dossier  # noqa: E402
from app.push import digest, enrich  # noqa: E402
from app.sources import announcements, prices, screener  # noqa: E402


async def check() -> None:
    ok = lambda b: "OK " if b else "FAIL"
    h = await prices.history("RELIANCE")
    print(ok(h and len(h["rows"]) > 100), "Yahoo EOD prices", len(h["rows"]) if h else 0, "rows")
    rows, st = await announcements.for_symbol("RELIANCE", "500325", 24 * 7)
    print(ok(st in ("live", "cache")), f"Announcements ({st})", len(rows), "in 7d", f"via {rows[0]['source']}" if rows else "")
    sc = await screener.company("ASIANPAINT")
    print(ok(sc and sc["quarters"]["periods"]), "screener.in", sc and len(sc["docs"]["concalls"]), "concalls listed")
    try:
        out = await llm.call("ping", 'Return JSON {"ok": true}', tier="cheap")
        print(ok(out.get("ok")), "LLM cheap tier", config.MODEL_CHEAP)
    except Exception as e:
        print("FAIL LLM", e)


async def warm() -> None:
    t = time.time()
    p = config.load_portfolio()
    for hours in (24, 72, 168, 720):
        d = await digest.build(hours)
        print(f"digest {hours}h: {len(d['items'])} filings, {d['counts']}")
    act = [i for i in d["items"] if i["tier"] == "act"]
    print(f"enriching {len(act)} 'needs you' items")
    for it in act:
        try:
            await enrich.enrich(it)
        except Exception as e:   # one bad PDF shouldn't stop the snapshot
            print("  skip", it["symbol"], it["category"], e)
    for sym in p["research_demo"]:
        print("dossier", sym)
        async for ev in dossier.stream(sym):
            e = json.loads(ev)
            if e["type"] in ("status", "error"):
                print("  ", e.get("text"))
    n = db.dump_seed(["ann", "prices", "screener_v2", "card_results"])
    print(f"wrote {n} rows to {config.SEED_PATH} ({config.SEED_PATH.stat().st_size / 1e6:.1f} MB) in {time.time() - t:.0f}s")
    print(json.dumps(llm.usage_summary(), indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    asyncio.run(check() if a.check else warm())
