# FINN — an investor's filing desk

A mobile-first prototype with an 18-stock mock portfolio, a prioritized filing inbox, configurable alerts, and company research from annual reports and earnings-call transcripts.

## Start here
Requires Python 3.12+ and Node 22+.
```bash
bash scripts/run.sh setup
# Edit .env locally; never commit it.
bash scripts/run.sh check
bash scripts/run.sh start
```
Open http://localhost:8000. On a phone on the same Wi-Fi, use your computer's LAN IP and port 8000. Voice input may require HTTPS.

To explore the interface without keys:
```bash
bash scripts/run.sh demo
```
This mode uses synthetic, visibly labeled data. It is not evidence of live research accuracy.

## Credentials
Copy .env.example to .env (setup does this only if .env is absent).

- GEMINI_API_KEY: required for live model extraction and research.
- MODEL_CHEAP / MODEL_STRONG: configure model identifiers available to your account.
- TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID: optional notifications. Create your own bot with BotFather and start a chat with it.
- CRON_TOKEN: choose a long random value and use the same value in GitHub Actions.
- TAVILY_API_KEY: optional web background for newly appointed executives (push side).

Never include credentials in the repository, screenshots, AI history exports, or covering email.

## What works
- **Brief (push):** pick 24h, 3d, 7d or 30d. Every filing is classified (rules first, a cheap model only for leftovers), scored with visible reasons, and tiered into Needs you / Worth knowing / Filed away. Swipe or tap Done, Keep, Less like this; "less" re-ranks that category for you.
- **Results cards:** the model copies numbers off the filing; Python computes EBITDA (PBT + finance cost + D&A − other income − exceptional), QoQ, YoY and margins, then cross-checks revenue against screener when period and basis match. Lender status comes from the balance sheet, not the model.
- **Management changes:** person, role, effective date and the disclosed profile; optional web background (Tavily) and a LinkedIn search link.
- **Alerts:** your thresholds for volume (× N-day average) and price (± %), plus filing categories you care about; deduped, optionally pushed to Telegram on a GitHub Actions schedule.
- **Research (pull), any NSE symbol:** snapshot, financials, trajectory, balance sheet and cash quality are computed in Python from filed numbers (0 model calls).
- **Promised vs delivered, decided in Python** (`backend/app/pull/promises.py`): a cheap model extracts each guidance statement (metric, target, period, verbatim quote, page) from the last four call transcripts. Python parses the target into a band, maps it to a reported series (operating profit divided by sales as an EBITDA margin proxy, sales YoY for revenue growth, net profit YoY for PAT growth), picks the quarters it covers, and returns Delivered / On track / Near miss / At risk / Missed / Off track / Too early. Repeats across calls are merged, and a moved goalpost (a lowered floor or dropped top end) is flagged. Targets the financials can't test, like volumes, are listed as such rather than guessed.
- One strong-model call writes story-vs-numbers, bull/bear and what to watch over a compact evidence pack; any row whose page citation doesn't exist is dropped.
- Grounded follow-up Q&A (BM25 over the company's own documents, page-cited, rejected if it cites a page it wasn't shown). Voice in and Listen out.
- Cost: rules before models, two model tiers, content-hash caching, ranked pages instead of whole PDFs; Setup shows the live call/token/cache-hit meter.

## Limitations (deliberate)
- Margin guidance uses operating profit divided by sales as a proxy. A company’s disclosed EBITDA definition may differ.
- Render uses a browser cookie to separate reviewer settings, triage, and manual alerts. Scheduled scans use the default portfolio and rules. To test isolation locally, set FINN_ISOLATE_REVIEWERS=1 before starting.
- Exchange feeds can refuse some cloud IPs; the deploy targets Render Singapore and falls back to BSE and then to cached data, with a visible banner when coverage is partial.

## Validate and prepare
```bash
bash scripts/run.sh test
bash scripts/run.sh check
bash scripts/run.sh snapshot
```
Snapshot requires successful preflight and may consume model quota. It creates data/seed.jsonl.gz. Inspect its contents and dates before committing it. Cached filings remain constrained to the selected time window.

The hosted demo serves dated cached filings and prices while external feeds refresh. Asian Paints opens a dated research snapshot built from the original filings and call transcripts. **Refresh live** requests a fresh analysis. Follow-up questions on the snapshot use a smaller set of cited excerpts.

## Deploy
1. Create a GitHub repository and push this folder, excluding .env, .venv and local databases.
2. Create a Render Blueprint from render.yaml. Set the model key and any optional Telegram values in Render.
3. Open /api/health and test the deployed phone experience.
4. For scheduled alerts, set GitHub repository secrets FINN_URL and CRON_TOKEN. Match CRON_TOKEN to Render.
5. Run the workflow manually, confirm its success, then verify an actual Telegram delivery when a configured rule matches.

Hosting availability and plan terms may vary. The bundled Dockerfile builds and serves the frontend and API together.

See SUBMISSION.md for the final review sequence and WRITEUP.md for the covering email.
