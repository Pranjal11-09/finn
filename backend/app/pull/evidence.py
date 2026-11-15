"""Fail closed on citations. Promise verdicts never come from the model (see promises.py)."""
import re

_CITE = re.compile(r"\[?(S\d+)\s+p\.(\d+)\]?")


def _valid(cite, pages) -> bool:
    m = _CITE.fullmatch(str(cite or "").strip())
    return bool(m and m[1] in pages and 1 <= int(m[2]) <= len(pages[m[1]]))


def validate_synthesis(syn, pages):
    if not isinstance(syn, dict):
        return {"error": "The model did not return a valid evidence summary."}
    # Anything verdict-like the model volunteers is discarded: verdicts are computed, not generated.
    for k in ("promise_vs_delivery", "scorecard"):
        syn.pop(k, None)
    for k in ("narrative_vs_numbers", "guidance_now"):
        rows = syn.get(k) if isinstance(syn.get(k), list) else []
        clean = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not _valid(row.get("cite"), pages):
                continue                      # a claim we can't point to a real page doesn't get shown
            clean.append(row)
        syn[k] = clean
    for k in ("bull", "bear", "watch"):
        syn[k] = [x for x in (syn.get(k) or []) if isinstance(x, str)][:3]
    return syn


def validate_answer(out, hits):
    if not isinstance(out, dict) or not isinstance(out.get("answer"), str):
        return {"answer": "Could not validate this answer.", "cites": []}
    answer = out["answer"]
    cited = re.findall(r"\[(S\d+)\s+p\.(\d+)\]", answer)
    allowed = {(h["sid"], h["page"]) for h in hits}
    if not cited or any((sid, int(page)) not in allowed for sid, page in cited):
        return {"answer": "I could not validate the answer against retrieved document pages. Please narrow the question or inspect the sources.", "cites": []}
    out["confidence"] = "unverified"
    return out
