# tech-news

Detailed daily tech briefing → Telegram, ~7:00 AM IST via GitHub Actions.

Last 24h of feed entries across AI, software & dev, hardware and security,
summarized into a sectioned briefing (AI / SOFTWARE & DEV / HARDWARE /
INDUSTRY / SECURITY) — each story with what happened, why it matters,
and a link.

Part of the personal-agents fleet (`[feeds] → [summarize] → [Telegram]`):
one agent, one task, one bot — `@jayanth_tech_briefing_bot`.

- Schedule: `.github/workflows/tech-news.yml` (`29 1 * * *` UTC = 06:59 IST)
- Feeds: `FEEDS` dict in `tech_news.py`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Run now: `gh workflow run tech-news.yml -R astroboy1183/tech-news`
