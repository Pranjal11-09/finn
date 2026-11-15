"""Check real source availability without sending Telegram messages."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import config, llm
from app.sources import prices, announcements, screener

async def main():
    results = {}
    for holding in config.load_portfolio()["portfolio"]:
        symbol = holding["symbol"]
        data = await prices.history(symbol)
        results[f"prices:{symbol}"] = bool(data and not data.get("stale") and len(data.get("rows", [])) > 20)
    rows, status = await announcements.for_symbol("RELIANCE", "500325", 168)
    results["announcements"] = status in ("live", "cache")
    for symbol in config.load_portfolio()["research_demo"]:
        data = await screener.company(symbol)
        results[f"research:{symbol}"] = bool(data and sum(bool(c.get("transcript")) for c in data["docs"]["concalls"]) >= 4 and data["quarters"]["periods"])
    try:
        results["model"] = (await llm.call("preflight", 'Return JSON {"ok":true}')).get("ok") is True
    except Exception:
        results["model"] = False
    for name, ok in results.items():
        print(f'{"PASS" if ok else "FAIL"} {name}')
    print("Telegram configured:", bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID))
    print("No Telegram message was sent.")
    return 0 if all(results.values()) else 1
if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
