"""Grounded follow-up questions. BM25 over the company's own documents (no embeddings, no vector DB — the corpus is
~4 transcripts + 1 AR, lexical retrieval is enough and costs nothing), then one model call that must cite pages."""
from __future__ import annotations

import asyncio
import math
from collections import Counter

from .. import db, llm
from ..sources import screener
from . import docs as D
from . import metrics as M
from .evidence import validate_answer

QA_SYS = ("Answer an investor's question about one company using ONLY the excerpts and numbers given. "
          "Cite every sentence with [S# p.#] or [N:quarterly]/[N:annual]. If the excerpts don't answer it, say so "
          "plainly and say what document would. Max 120 words. No preamble.")


def bm25(query: str, chunks: list[dict], k: int = 6) -> list[dict]:
    docs = [D.tokenize(c["text"]) for c in chunks]
    if not docs:
        return []
    N = len(docs)
    avg = sum(len(d) for d in docs) / N
    df = Counter(t for d in docs for t in set(d))
    q = D.tokenize(query)
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        scored.append((s, i))
    scored.sort(reverse=True)
    return [chunks[i] for s, i in scored[:k] if s > 0]


async def answer(symbol: str, question: str) -> dict:
    symbol = symbol.upper()
    store = db.kv_get_stale("chunks", symbol)
    if not store:
        return {"answer": "Open the research view for this company first so I can read its documents.", "cites": []}
    hits = bm25(question, store[0]["chunks"])
    sc = await screener.company(symbol)
    numbers = M.actuals_table(sc) if sc else ""
    ctx = "\n\n".join(f"[{h['sid']} p.{h['page']}] ({h['title']})\n{h['text']}" for h in hits)
    try:
        out = await asyncio.wait_for(llm.call("qa", f"QUESTION: {question}\n\nNUMBERS:\n{numbers}\n\nEXCERPTS:\n{ctx}\n\n"
                                   'Return JSON {"answer": "...", "confidence": "high|medium|low"}',
                             system=QA_SYS, tier="cheap", version="v3", max_tokens=800), timeout=45)
    except asyncio.TimeoutError:
        return {"answer": "The model took too long. Please retry or narrow your question.", "cites": []}
    except llm.LLMUnavailable as e:
        return {"answer": f"Model unavailable: {e}", "cites": []}
    out = validate_answer(out, hits)
    out["cites"] = [{"sid": h["sid"], "page": h["page"], "title": h["title"]} for h in hits]
    return out
