"""Model router.

Design rules (this is where the cost story lives):
  1. Rules before models. Callers try deterministic logic first; the LLM sees only what rules can't resolve.
  2. Two tiers. `cheap` (Flash-Lite class) for extraction/classification; `strong` (Flash class) only for the
     final reasoning step of a research dossier and for grounded Q&A.
  3. Everything is cached on (model, prompt-version, input hash). Re-running a dossier costs zero.
  4. Small inputs. Callers pre-select pages/chunks; models never see a whole 300-page annual report.
  5. Every call is metered into llm_usage so the app can show its own bill.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from . import config, db

_sem = asyncio.Semaphore(4)       # free-tier friendly concurrency


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    if config.LLM_PROVIDER == "off":
        return False
    if config.LLM_PROVIDER == "gemini":
        return bool(config.GEMINI_API_KEY)
    return bool(config.OPENAI_API_KEY) or "localhost" in config.OPENAI_BASE_URL


def _model(tier: str) -> str:
    return config.MODEL_STRONG if tier == "strong" else config.MODEL_CHEAP


def _parse_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise


async def _gemini(model: str, system: str, prompt: str, want_json: bool, max_tokens: int) -> tuple[str, int, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # thinking models spend output budget on reasoning first; the cap is a ceiling, not a cost
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens * 4},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(url, json=body, headers={"x-goog-api-key": config.GEMINI_API_KEY})
    if r.status_code >= 400:
        raise httpx.HTTPStatusError(r.text[:300], request=r.request, response=r)
    d = r.json()
    parts = d.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = d.get("usageMetadata", {})
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


async def _openai(model: str, system: str, prompt: str, want_json: bool, max_tokens: int) -> tuple[str, int, int]:
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {"model": model, "messages": msgs, "temperature": 0.1, "max_tokens": max_tokens}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{config.OPENAI_BASE_URL}/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"})
    if r.status_code >= 400:
        raise httpx.HTTPStatusError(r.text[:300], request=r.request, response=r)
    d = r.json()
    u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _fixture(task: str) -> Any:
    p = config.FIXTURE_DIR / "llm" / f"{task}.json"
    if p.exists():
        return json.loads(p.read_text())
    raise LLMUnavailable(f"no LLM configured (and no fixture for {task})")


async def call(task: str, prompt: str, *, system: str = "", tier: str = "cheap", want_json: bool = True,
               version: str = "v1", max_tokens: int = 2048) -> Any:
    model = _model(tier)
    key = db.h(model, task, version, system, prompt)
    hit = db.kv_get("llm", key)
    if hit is not None:
        db.execute("INSERT INTO llm_usage VALUES (?,?,?,?,?,?,?,?)", (time.time(), task, model, tier, 0, 0, 1, 0))
        return hit[0]
    if not available():
        if config.FIXTURES:
            return _fixture(task)
        raise LLMUnavailable("Set GEMINI_API_KEY (or LLM_PROVIDER=openai + OPENAI_API_KEY)")

    fn = _gemini if config.LLM_PROVIDER == "gemini" else _openai
    t0 = time.time()
    last: Exception | None = None
    models = [model] + ([config.MODEL_CHEAP] if tier == "strong" else [])   # degrade strong -> cheap on quota
    for m in models:
        for attempt in range(3):
            try:
                async with _sem:
                    text, tin, tout = await fn(m, system, prompt, want_json, max_tokens)
                out = _parse_json(text) if want_json else text.strip()
                db.kv_set("llm", key, out)
                db.execute("INSERT INTO llm_usage VALUES (?,?,?,?,?,?,?,?)",
                           (time.time(), task, m, tier, tin, tout, 0, int((time.time() - t0) * 1000)))
                return out
            except httpx.HTTPStatusError as e:
                last = e
                code = e.response.status_code
                if code in (429, 500, 503):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                break
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as e:
                last = e
                await asyncio.sleep(1)
    raise LLMUnavailable(f"{task}: {last}")


def usage_summary() -> dict:
    rows = db.execute("SELECT tier, model, COUNT(*), SUM(in_tok), SUM(out_tok), SUM(cached) FROM llm_usage "
                      "GROUP BY tier, model")
    out = [{"tier": r[0], "model": r[1], "calls": r[2], "in_tokens": r[3] or 0, "out_tokens": r[4] or 0,
            "cache_hits": r[5] or 0} for r in rows]
    rule = db.kv_get_stale("stats", "classifier") or ({"rules": 0, "llm": 0}, 0)
    return {"models": out, "classifier": rule[0], "provider": config.LLM_PROVIDER,
            "cheap": config.MODEL_CHEAP, "strong": config.MODEL_STRONG, "llm_ready": available()}
