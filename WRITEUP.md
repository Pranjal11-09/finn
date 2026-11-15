To: assessment@enam.com
Subject: IIT Delhi – AI Engineer - 2027

Hello ENAM team,

Here is my submission for FINN.

- Try it on your phone: [INSERT DEPLOYED HTTPS URL]
- Repository: [INSERT REPOSITORY URL]
- AI build history: [INSERT SHARE LINKS / ATTACHED EXPORTS]

What I built
FINN is a filing desk. The Brief opens to one sentence ("4 things need you: 1 result, 2 management changes, 1 unusual move") and a short stack of cards; everything routine is folded away. Each card earns its place with visible reasons ("CEO/CFO level", "mid-cap: more material", "stock −4.2% today"). Results cards show Revenue, EBITDA, PBT and PAT, QoQ and YoY; management changes show who the person is. You swipe a card away when you're done, and "less like this" re-ranks that category for you. Alerts fire on thresholds you set (volume × average, ±% move, filing types) and can push to Telegram.

Research accepts NSE symbols with available financials and documents. In Asian Paints’ Q2 FY27 call, management reiterated an 18–20% full-year EBITDA margin band. FINN shows 18.2% for the first two quarters using operating profit divided by sales as an EBITDA margin proxy, with Q2 at 15.6%. Open the transcript citation to see the target and the ledger to see how the comparison was calculated.

Key decisions
1. Models read; Python judges. A cheap model extracts numbers and guidance statements. Python does all arithmetic and every delivered/missed verdict, so the same extracted inputs give the same verdict and the calculation can be inspected.
2. Rules before models. Most filings are classified by the exchange's own subject line and a few patterns; the model sees only the leftovers, batched. One strong-model call per dossier, everything cached by content hash. The Setup tab shows the running bill.
3. Say "can't check" instead of guessing. Promises the financials can't test (volumes, store counts) are listed as such; narrative comparisons and guidance entries with invalid page references are dropped.

Left out on purpose
User accounts, native apps, intraday data, a vector database (four transcripts and an annual report don't need one; BM25 is free and inspectable), and broker/news sources on the research side.

Next
Segment-level promise checks from investor presentations, a results-day mode that pre-reads the board-meeting intimation, and persistent accounts.

Pranjal Gupta
B.Tech Textile Engineering (Minor in Design), IIT Delhi
