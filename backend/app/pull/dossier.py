"""Research dossier, streamed section by section.

  stage 0  screener fundamentals             -> 5 deterministic sections, instantly       (0 LLM calls)
  stage 1  per-transcript guidance extraction -> map step, cheap model, cached per doc    (~4 cheap calls)
           annual report business snapshot   -> cheap model on ~5 ranked pages           (1 cheap call)
  stage 2  promised-vs-delivered: parsed + judged in Python (promises.py)         (0 LLM calls)
  stage 3  synthesis: narrative-vs-numbers, guidance on the table, bull/bear
           -> ONE strong-model call over a compact evidence pack (~8-12k tokens)          (1 strong call)
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from .. import config, db, llm
from ..sources import screener
from . import docs as D
from . import metrics as M
from . import promises as P
from .evidence import validate_synthesis, validate_guidance

GUIDANCE_SYS = ("You extract forward-looking statements from Indian earnings-call transcripts. Quote management "
                "verbatim. Never infer numbers that are not said. Ignore analysts' own estimates.")

GUIDANCE_PROMPT = """Transcript: {title}
From the excerpt below, extract:
1. guidance: every explicit forward-looking target management gave (growth, margin, capex, volumes, market share, debt, launches).
2. claims: management's main narrative assertions about the business right now (demand, share gains, pricing, cost) — max 5.
3. pushback: topics analysts pressed hardest on — max 4.
Return JSON:
{{"quarter":"e.g. Q2 FY26 (the quarter being discussed)",
 "guidance":[{{"metric":"revenue_growth|margin|pat_growth|capex|volume|debt|other","target":"e.g. 12-14% or ₹2,000 Cr",
   "period":"e.g. FY26 / H2 FY26 / next 2-3 years / unspecified","quote":"verbatim, <=30 words","speaker":"role","page":<int>,
   "quantified":true/false}}],
 "claims":[{{"topic":"","quote":"verbatim <=25 words","page":<int>}}],
 "pushback":[{{"topic":"","gist":"<=15 words","page":<int>}}],
 "tone":"confident|cautious|defensive|mixed"}}

EXCERPT:
{text}"""

BUSINESS_PROMPT = """Using ONLY the text below (company description + annual report pages), describe the business.
Return JSON: {{"what":"<=2 sentences: what it sells, to whom, how it makes money",
 "segments":[{{"name":"","share_pct":<number or null>,"note":"<=10 words","cite":"S# p.#"}}],
 "mix_basis":"period the mix refers to, or null",
 "drivers":["<=12 words each, max 3, each ending with a cite like [S# p.#]"]}}
Do not use any knowledge beyond the text.

{text}"""

SYNTH_SYS = ("You are a sceptical buy-side analyst. You only use the evidence pack provided — no outside knowledge "
             "about this company, no news, no broker views. Every bullet must carry at least one citation tag: "
             "[S# p.#] for a document page or [N:quarterly]/[N:annual]/[N:flags] for the computed numbers. "
             "If evidence is missing, say 'not disclosed'. Be terse: write like a PM's margin note, not an essay.")

SYNTH_PROMPT = """Company: {name} ({symbol})

=== COMPUTED NUMBERS (authoritative; from filed financials) ===
{actuals}

=== RULE FLAGS ===
{flags}

=== PROMISE CHECK (computed in Python against reported numbers; authoritative — do not re-judge) ===
{promises}

=== GUIDANCE & CLAIMS EXTRACTED FROM TRANSCRIPTS (oldest → newest) ===
{ledger}

TASK
A. narrative_vs_numbers: up to 4 management claims (demand, share, pricing, cost) where the computed numbers agree
   or diverge. Prefer divergences — that is what the reader is paying for.
B. guidance_now: the latest outstanding guidance (max 5).
C. bull / bear: 3 bullets each, each grounded; use the promise check where relevant.
D. watch: 3 concrete things to check next quarter (a number and a threshold, not a theme).

Return JSON:
{{"narrative_vs_numbers":[{{"claim":"","cite":"S# p.#","numbers":"","num_cite":"N:quarterly","agree":"yes|partly|no"}}],
 "guidance_now":[{{"metric":"","target":"","period":"","cite":"S# p.#"}}],
 "bull":[""],"bear":[""],"watch":[""]}}"""


def _promise_text(pc: dict) -> str:
    out = [f"- {r['verdict'].upper()}: {r['promise']} (said in {r['repeats']} call(s), latest [{r['cite']}]) — actual "
           f"{r['actual']}{'; ' + r['comment'] if r.get('comment') else ''}" for r in pc.get("rows", [])]
    out += [f"- REVISION: {r['text']} [{r['cite']}]" for r in pc.get("revisions", [])]
    return "\n".join(out) or "- none extracted"


def _ev(kind: str, **data) -> str:
    return json.dumps({"type": kind, **data}, default=str)


async def _guidance(doc: dict, pages: list[str]) -> dict:
    if not pages:
        return {"sid": doc["sid"], "error": "could not read transcript"}
    text, used = D.excerpt(pages, D.GUIDANCE_TERMS, k=8, head=3)
    text = text[:32000]
    try:
        out = await llm.call("guidance_extract", GUIDANCE_PROMPT.format(title=doc["title"], text=text),
                             system=GUIDANCE_SYS, tier="cheap", version="v2", max_tokens=3000)
    except llm.LLMUnavailable as e:
        return {"sid": doc["sid"], "error": str(e)}
    out = validate_guidance(out, pages)
    out["sid"], out["title"], out["pages_read"], out["pages_total"] = doc["sid"], doc["title"], len(used), len(pages)
    return out


async def _business(sc: dict, ar: dict | None, ar_pages: list[str]) -> dict:
    text = f"[company description]\n{sc.get('about', '')}\n"
    if ar and ar_pages:
        ex, _ = D.excerpt(ar_pages, D.BUSINESS_TERMS, k=5, per_page=3000)
        text += f"\n[{ar['sid']} = {ar['title']}]\n{ex}"
    try:
        return await llm.call("business_snapshot", BUSINESS_PROMPT.format(text=text[:22000]), tier="cheap")
    except llm.LLMUnavailable as e:
        return {"what": sc.get("about", ""), "segments": [], "error": str(e)}


def _ledger_text(gs: list[dict]) -> str:
    lines = []
    for g in reversed(gs):          # transcripts are newest-first from screener
        if g.get("error"):
            continue
        lines.append(f"\n## {g['sid']} · {g.get('title')} · discussing {g.get('quarter')} · tone {g.get('tone')}")
        for x in g.get("guidance", []):
            lines.append(f"- GUIDE [{g['sid']} p.{x.get('page')}] {x.get('metric')}: {x.get('target')} for {x.get('period')}"
                         f" — \"{x.get('quote')}\" ({x.get('speaker')})")
        for x in g.get("claims", []):
            lines.append(f"- CLAIM [{g['sid']} p.{x.get('page')}] {x.get('topic')}: \"{x.get('quote')}\"")
        for x in g.get("pushback", []):
            lines.append(f"- ANALYSTS PRESSED [{g['sid']} p.{x.get('page')}] {x.get('topic')}: {x.get('gist')}")
    return "\n".join(lines)


async def stream(symbol: str, *, live: bool = False) -> AsyncIterator[str]:
    symbol = symbol.upper().strip()
    saved = db.kv_get("demo_dossier_v1", symbol) if config.FAST_FEEDS and not live else None
    if saved:
        yield _ev("snapshot", captured_at=saved[0]["created_at"])
        for event in saved[0]["events"]:
            yield json.dumps(event)
        yield _ev("status", stage="done", text="Saved research ready")
        return
    yield _ev("status", stage="fundamentals", text=f"Pulling {symbol} filings & financials")
    sc = await screener.company(symbol)
    if not sc or not sc["quarters"]["periods"]:
        yield _ev("error", text=f"No fundamentals found for {symbol}. Is it an NSE symbol?")
        return
    secs = {"snapshot": M.snapshot(sc), "financials": M.financials(sc), "trajectory": M.trajectory(sc),
            "balance_sheet": M.balance_sheet(sc), "cash_quality": M.cash_quality(sc)}
    yield _ev("meta", symbol=symbol, name=sc["name"], url=sc["url"], basis=sc.get("basis"),
              financial=M.is_financial(sc))
    for k, v in secs.items():
        yield _ev("section", key=k, data=v)

    docs = D.select_docs(sc)
    yield _ev("sources", docs=docs)
    if not docs:
        yield _ev("status", stage="done", text="No transcripts/annual reports linked — showing numbers only.")
        return
    yield _ev("status", stage="reading", text=f"Reading {len(docs)} primary documents")
    pages = await asyncio.gather(*(D.load(d) for d in docs))
    by_sid = {d["sid"]: p for d, p in zip(docs, pages)}
    yield _ev("coverage", documents=[{"sid": d["sid"], "title": d["title"], "pages_loaded": len(by_sid[d["sid"]])} for d in docs])
    # build retrieval chunks for follow-up Q&A
    all_chunks = [c for d in docs for c in D.chunks(d, by_sid[d["sid"]])]
    db.kv_set("chunks", symbol, {"docs": docs, "chunks": all_chunks})

    transcripts = [d for d in docs if d["kind"] == "transcript"]
    ar = next((d for d in docs if d["kind"] == "annual_report"), None)
    yield _ev("status", stage="extracting", text=f"Extracting guidance from {len(transcripts)} calls")
    tasks = [asyncio.create_task(_guidance(d, by_sid[d["sid"]])) for d in transcripts]
    biz_task = asyncio.create_task(_business(sc, ar, by_sid.get(ar["sid"], []) if ar else []))
    gs = []
    for t in asyncio.as_completed(tasks):
        g = await t
        gs.append(g)
        yield _ev("guidance", data=g)
    order = {d["sid"]: i for i, d in enumerate(transcripts)}
    gs.sort(key=lambda g: order.get(g["sid"], 99))
    pc = P.check(gs, sc, transcripts)
    yield _ev("section", key="promises", data=pc)
    yield _ev("section", key="business", data=await biz_task)

    if not any(g.get("guidance") or g.get("claims") for g in gs):
        yield _ev("status", stage="done", text="Couldn't extract guidance (LLM unavailable or transcripts unreadable).")
        return
    yield _ev("status", stage="synthesis", text="Weighing their story against the numbers")
    try:
        syn = await asyncio.wait_for(llm.call("dossier_synthesis", SYNTH_PROMPT.format(
            name=sc["name"], symbol=symbol, actuals=M.actuals_table(sc),
            flags=M.flags_text(list(secs.values())), promises=_promise_text(pc), ledger=_ledger_text(gs)),
            system=SYNTH_SYS, tier="strong", version="v4", max_tokens=4000), timeout=30)
        yield _ev("section", key="synthesis", data=validate_synthesis(syn, by_sid))
    except (TimeoutError, llm.LLMUnavailable):
        yield _ev("section", key="synthesis", data={"error": "The narrative analysis was unavailable. The promise ledger and financials are ready below."})
    yield _ev("status", stage="done", text="Done")
