"""Primary-source document set for a company: last N concall transcripts + latest annual report.
Each doc gets a stable short id (S1, S2...) that every citation in the UI points back to."""
from __future__ import annotations

import asyncio
import re

from ..sources import pdftext

GUIDANCE_TERMS = {"guidance": 4, "guide": 3, "expect": 2, "target": 2, "outlook": 3, "going forward": 3,
                  "next year": 2, "fy2": 1.5, "margin": 1.5, "growth": 1, "capex": 2, "double digit": 3,
                  "double-digit": 3, "aspire": 2, "aim": 1, "ebitda": 1.5, "visibility": 2, "pipeline": 1}
BUSINESS_TERMS = {"segment": 3, "revenue mix": 4, "business overview": 4, "our businesses": 3, "contribution": 1.5,
                  "share of revenue": 4, "segment revenue": 5, "geograph": 1.5, "product portfolio": 2,
                  "management discussion": 3, "industry structure": 2}


def select_docs(sc: dict, n_calls: int = 4) -> list[dict]:
    docs = []
    calls = [c for c in sc["docs"]["concalls"] if c.get("transcript")][:n_calls]
    for c in calls:
        docs.append({"kind": "transcript", "title": f"Concall transcript · {c['date']}", "date": c["date"],
                     "url": c["transcript"]})
    ars = sc["docs"]["annual_reports"][:1]
    for a in ars:
        docs.append({"kind": "annual_report", "title": f"Annual report · {a['title'].split(' from')[0]}", "url": a["url"]})
    for i, d in enumerate(docs):
        d["sid"] = f"S{i + 1}"
    return docs


async def load(doc: dict) -> list[str]:
    cap = 40 if doc["kind"] == "transcript" else 160
    try:
        return await asyncio.wait_for(pdftext.pages(doc["url"], max_pages=cap), timeout=14)
    except asyncio.TimeoutError:
        return []


def excerpt(pages: list[str], weights: dict, k: int, head: int = 0, per_page: int = 3500) -> tuple[str, list[int]]:
    idx = set(pdftext.rank_pages(pages, weights, k=k))
    idx |= set(range(1, min(head + 1, len(pages))))          # opening remarks (skip cover page)
    idx = sorted(idx)
    txt = "\n\n".join(f"[p.{i + 1}]\n{pages[i][:per_page]}" for i in idx)
    return txt, [i + 1 for i in idx]


def chunks(doc: dict, pages: list[str], size: int = 900) -> list[dict]:
    out = []
    for pi, p in enumerate(pages):
        words = p.split()
        for j in range(0, len(words), size // 6):
            w = words[j:j + size // 6 + 20]
            if len(w) < 25:
                continue
            out.append({"sid": doc["sid"], "page": pi + 1, "title": doc["title"], "text": " ".join(w)})
    return out


_tok = re.compile(r"[a-z0-9%]+")


def tokenize(s: str) -> list[str]:
    return _tok.findall(s.lower())
