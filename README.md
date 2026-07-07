# tech-news

Detailed daily tech briefing → Telegram, ~7:00 AM IST via GitHub Actions.

Last 24h of feed entries across AI, software & dev, hardware and
security, summarized into a sectioned briefing — each story with what
happened, why it matters, and a link. One agent, one task, one bot:
`@jayanth_tech_briefing_bot`.

## How the code works

`tech_news.py`, in pipeline order:

- **`FEEDS`** — `{category: [feed urls]}` across AI, Software & Dev,
  Hardware, Security (two feeds each). `ENTRIES_PER_FEED = 12`,
  `SUMMARY_CHARS = 300` and `LOOKBACK_HOURS = 24` cap the prompt size.
- **`clean(html)`** — feed summaries arrive as HTML; a regex strips tags
  and collapses whitespace.
- **`fresh(entry, cutoff)`** — keeps entries newer than the 24h cutoff
  using the feed's published/updated stamp. Entries with *no* date are
  KEPT — news feeds are erratic about dates and dropping undated items
  loses stories (contrast with eng-blogs, which drops them).
- **`gather_stories()`** — per-feed `try/except` (a dead feed is
  skipped), collecting `{title, summary, link}` per fresh entry.
- **`summarize(stories)`** — one model call with all candidates. The
  prompt fixes the sections (AI / SOFTWARE & DEV / HARDWARE / INDUSTRY /
  SECURITY), 3–5 ranked stories each, dedupes cross-feed coverage, and
  has two special rules: INDUSTRY has no feeds of its own (business/
  acquisition stories get pulled from other categories' candidates), and
  Hacker News entries have no summaries (judged by title, only clearly
  significant ones included).
- **`main()`** — gather → summarize → send with a scanned-count header;
  all-feeds-dead days send a one-liner without a model call.
- **`agentlib.py`** (vendored) — `ask_llm()` one-shot model call;
  `send_telegram()` chunked sends.

## Design notes

- Two crons + dedupe guard: backup at 07:59 IST delivers only if the
  06:59 primary was dropped or failed (fleet lesson from 2026-07-04).

## Ops

- Schedule: `.github/workflows/tech-news.yml` (`29 1 * * *` UTC = 06:59 IST; backup 07:59)
- Run now: `gh workflow run tech-news.yml -R astroboy1183/tech-news`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Feeds: `FEEDS` dict in `tech_news.py`
