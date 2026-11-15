from __future__ import annotations

import asyncio
import os
import re
import secrets

import httpx
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, llm
from .http import client
from .pull import dossier, qa
from .push import alerts, digest, enrich

app = FastAPI(title="FINN", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def isolate_reviewer(request: Request, call_next):
    if not config.ISOLATE_REVIEWERS or request.url.path.startswith(("/api/cron/", "/assets/")):
        return await call_next(request)
    cookie = request.cookies.get("finn_reviewer", "")
    valid = bool(re.fullmatch(r"[0-9a-f]{32}", cookie))
    scope = cookie if valid else secrets.token_hex(16)
    token = db.reviewer.set(scope)
    try:
        response = await call_next(request)
    finally:
        db.reviewer.reset(token)
    if not valid:
        response.set_cookie("finn_reviewer", scope, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https", max_age=7 * 24 * 3600)
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "release": "evidence-mobile-v2", "llm": llm.available(), "fixtures": config.FIXTURES, "fast_feeds": config.FAST_FEEDS,
            "telegram": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)}


@app.get("/api/portfolio")
async def portfolio():
    s = db.get_settings()
    return {"holdings": digest.holdings(), "tape": list((await digest.tape(s["volume_lookback"])).values()),
            "research_demo": config.load_portfolio().get("research_demo", [])}


@app.get("/api/digest")
async def get_digest(hours: int = Query(24, ge=1, le=24 * 30)):
    return await digest.build(hours)


@app.get("/api/item/enrich")
async def item_enrich(id: str):
    hit = db.kv_get_stale("item", id)
    if not hit:
        raise HTTPException(404, "unknown item — reload the digest")
    try:
        return await asyncio.wait_for(enrich.enrich(hit[0]), timeout=12)
    except TimeoutError:
        return {"id": id, "line": hit[0].get("text") or hit[0].get("headline"),
                "error": "Filing enrichment took too long. Open the original filing to see the source."}


@app.post("/api/triage")
def post_triage(body: dict = Body(...)):
    if body.get("state") not in ("done", "keep", "less", "more", "new"):
        raise HTTPException(400, "bad state")
    return digest.triage(body["id"], body["state"])


@app.get("/api/alerts")
def get_alerts():
    return {"alerts": alerts.recent(), "settings": db.get_settings()}


@app.post("/api/alerts/scan")
async def scan_now():
    return await alerts.scan(push=True)


@app.get("/api/cron/scan")
async def cron_scan(token: str = ""):
    if not config.CRON_TOKEN or token != config.CRON_TOKEN:
        raise HTTPException(403)
    return await alerts.scan(push=True)


@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.post("/api/settings")
def post_settings(patch: dict = Body(...)):
    return db.save_settings(patch)


@app.get("/api/research/{symbol}/stream")
async def research_stream(symbol: str, live: bool = False):
    async def gen():
        async for ev in dossier.stream(symbol, live=live):
            yield f"data: {ev}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/research/{symbol}/ask")
async def research_ask(symbol: str, body: dict = Body(...)):
    q = (body.get("q") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    return await qa.answer(symbol, q, saved=body.get("saved") is True)


@app.get("/api/search")
async def search(q: str):
    if config.FIXTURES or len(q) < 2:
        return []
    try:
        r = await client().get("https://www.screener.in/api/company/search/", params={"q": q, "v": 3, "fts": 1})
        out = []
        for x in r.json()[:8]:
            parts = [p for p in (x.get("url") or "").split("/") if p]
            if len(parts) >= 2 and parts[0] == "company":
                out.append({"symbol": parts[1], "name": x.get("name")})
        return out
    except (httpx.HTTPError, ValueError):
        return []


@app.get("/api/usage")
def usage():
    return llm.usage_summary()


# ---- static SPA ----------------------------------------------------------------
if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = (config.WEB_DIST / path).resolve()
        if not f.is_relative_to(config.WEB_DIST.resolve()):
            raise HTTPException(404)
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.WEB_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
