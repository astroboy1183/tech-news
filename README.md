# tech-news

Detailed daily tech briefing → Telegram, ~7:00 AM IST via GitHub Actions.

Last 24h of feed entries across AI, software & dev, hardware and security,
summarized by Claude into a sectioned briefing (AI / SOFTWARE & DEV /
HARDWARE / INDUSTRY / SECURITY) — each story with what happened, why it
matters, and a link.

Same pattern as the other personal agents (`[feeds] → [Claude] → [Telegram]`);
full fleet reference lives in `~/Desktop/morning-mail-setup.md` on the laptop.

- Schedule: `.github/workflows/tech-news.yml` (`29 1 * * *` UTC = 06:59 IST)
- Feeds: `FEEDS` dict in `tech_news.py`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Run now: `gh workflow run tech-news.yml -R astroboy1183/tech-news`
