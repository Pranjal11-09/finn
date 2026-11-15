"""Read-only post-deploy smoke check: python3 scripts/smoke.py https://your-app.onrender.com"""
import json
import sys
import time
import urllib.request
import urllib.parse

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"

def get(path):
    started = time.monotonic()
    with urllib.request.urlopen(base + path, timeout=60) as response:
        body = response.read().decode()
    print(f"PASS {path.split('?')[0]} {time.monotonic() - started:.2f}s")
    return body

health = json.loads(get("/api/health"))
assert health["ok"] and not health["fixtures"], "Not a real-data deployment"
assert health.get("release") == "evidence-mobile-v2", "Old deployment is still serving"
assert '<div id="root"' in get("/"), "Missing frontend"
portfolio = json.loads(get("/api/portfolio"))
assert 15 <= len(portfolio["holdings"]) <= 20
for hours in (24, 72):
    digest = json.loads(get(f"/api/digest?hours={hours}"))
    assert isinstance(digest["items"], list) and digest["tape"], "Missing price data"
    print(f"  {len(digest['items'])} filings, {len(digest['tape'])} prices; feed status {set(digest['feed_status'].values())}")
    results = [i for i in digest["items"] if i["category"] == "results" and i.get("subtype") != "intimation"]
    if results:
        card = json.loads(get("/api/item/enrich?id=" + urllib.parse.quote(results[0]["id"]))) ["results"]
        assert card.get("metrics") and card.get("source_url") and card.get("verification"), card.get("error", "No evidence")
        print(f"  Results: {results[0]['symbol']}, {card['basis']}, source page {card['page']}")
stream = get("/api/research/ASIANPAINT/stream")
events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
assert any(e.get("stage") == "done" for e in events), "Research did not complete"
assert any(e.get("key") == "promises" for e in events), "Promise ledger missing"
assert not any(e["type"] == "error" for e in events), "Research returned an error"
print("PASS core deployment checks (not a physical-device or live-feed guarantee)")
