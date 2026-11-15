"""Fetch a filing PDF and return per-page text. Cached by URL; page-capped so a 400-page AR stays cheap."""
from __future__ import annotations

import asyncio
import io
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

import httpx

from .. import config, db
from ..http import client

MAX_BYTES = 60 * 1024 * 1024


def _extract(data: bytes, max_pages: int) -> list[str]:
    # Each worker owns a pure-Python reader. PDFium must not be invoked from
    # concurrent to_thread calls: even different documents share native state.
    from pypdf import PdfReader
    try:
        rd = PdfReader(io.BytesIO(data), strict=False)
        return [(p.extract_text() or "") for p in rd.pages[:max_pages]]
    except Exception:
        # Unreadable documents are missing evidence, not a server-wide failure.
        return []


async def pages(url: str, max_pages: int = 60) -> list[str]:
    if not url:
        return []
    if config.FIXTURES:
        p = config.FIXTURE_DIR / "pdf" / (db.h(url) + ".txt")
        if p.exists():
            return p.read_text().split("\f")
        name = "results" if "result" in url.lower() else ("transcript" if "transcript" in url.lower() else "")
        p = config.FIXTURE_DIR / "pdf" / f"{name}.txt"
        return p.read_text().split("\f") if name and p.exists() else []
    key = f"{db.h(url)}:{max_pages}"
    hit = db.kv_get("pdf", key)
    if hit:
        return hit[0]
    try:
        ref = "https://www.bseindia.com/" if "bseindia" in url else "https://www.nseindia.com/"
        r = await client().get(url, headers={"Referer": ref})
        r.raise_for_status()
        data = r.content[:MAX_BYTES]
        if not data.startswith(b"%PDF") and "annpdfopen.aspx" in url.lower():
            soup = BeautifulSoup(r.text, "html.parser")
            target = soup.select_one("iframe[src], embed[src], object[data]")
            if target:
                attachment = urljoin(str(r.url), target.get("src") or target.get("data"))
                r = await client().get(attachment, headers={"Referer": url})
                r.raise_for_status()
                data = r.content[:MAX_BYTES]
    except httpx.HTTPError:
        return []
    if not data.startswith(b"%PDF"):
        # some exchange "attachments" are XBRL/XML or HTML; keep the text, it's still useful
        txt = re.sub(r"<[^>]+>", " ", data[:200_000].decode("utf-8", "ignore"))
        out = [re.sub(r"\s+", " ", txt)]
    else:
        out = await asyncio.to_thread(_extract, data, max_pages)
    out = [re.sub(r"[ \t]+", " ", p) for p in out]
    db.kv_set("pdf", key, out)
    return out


def rank_pages(pgs: list[str], weights: dict[str, float], k: int = 4) -> list[int]:
    """Cheap lexical page selection so models only read the pages that matter."""
    scored = []
    for i, p in enumerate(pgs):
        low = p.lower()
        s = sum(w * low.count(term) for term, w in weights.items())
        scored.append((s, i))
    scored.sort(reverse=True)
    return sorted(i for s, i in scored[:k] if s > 0)
