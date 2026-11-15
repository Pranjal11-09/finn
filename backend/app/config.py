"""Runtime configuration. Everything is env-driven so the same image runs locally, on Render, or in tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# tiny .env loader (no python-dotenv dependency)
if (ROOT / ".env").exists():
    for _line in (ROOT / ".env").read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            if _v.strip():
                os.environ.setdefault(_k.strip(), _v.strip())
BACKEND = ROOT / "backend"
DATA_DIR = Path(os.getenv("FINN_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("FINN_DB", DATA_DIR / "finn.db"))
SEED_PATH = DATA_DIR / "seed.jsonl.gz"          # pre-warmed cache shipped with the repo (see scripts/snapshot.py)
WEB_DIST = ROOT / "web" / "dist"
FAST_FEEDS = os.getenv("FINN_FAST_FEEDS", "") == "1"
ISOLATE_REVIEWERS = os.getenv("FINN_ISOLATE_REVIEWERS", "") == "1"

# --- LLM routing -------------------------------------------------------------
# Two tiers. "cheap" does bulk extraction/classification, "strong" only does final reasoning.
# Any OpenAI-compatible endpoint works too (Groq, OpenRouter, Ollama) via LLM_PROVIDER=openai.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")           # gemini | openai | off
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL_CHEAP = os.getenv("MODEL_CHEAP", "gemini-flash-lite-latest")
MODEL_STRONG = os.getenv("MODEL_STRONG", "gemini-flash-latest")

# --- Push channels -----------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CRON_TOKEN = os.getenv("CRON_TOKEN", "")                 # protects /api/cron/scan
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")         # optional: web enrichment for people bios

# --- Test / dev --------------------------------------------------------------
FIXTURES = os.getenv("FINN_FIXTURES", "") == "1"        # serve synthetic fixtures (UI dev / tests only)
FIXTURE_DIR = BACKEND / "tests" / "fixtures"


def load_portfolio() -> dict:
    with open(BACKEND / "portfolio.json") as f:
        return json.load(f)
