#!/usr/bin/env python3
"""Tech briefing.

One detailed Telegram message every morning (~7:00 IST via GitHub Actions):
the last 24h of tech news across AI, software & dev, hardware, industry and
security — each story summarized with what happened, why it matters, and
a link.

Separate from the 6 AM morning briefing (morning-mail repo): own repo, own
bot, own schedule — it fails and gets fixed independently.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
from dotenv import load_dotenv

from agentlib import ask_llm, send_telegram

BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

# category → feeds; edit here to tune coverage
FEEDS = {
    "AI": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://venturebeat.com/category/ai/feed/",
    ],
    "Software & Dev": [
        "https://news.ycombinator.com/rss",
        "https://feeds.arstechnica.com/arstechnica/index",
    ],
    "Hardware": [
        "https://www.tomshardware.com/feeds/all",
        "https://www.theverge.com/rss/index.xml",
    ],
    "Security": [
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.bleepingcomputer.com/feed/",
    ],
}
ENTRIES_PER_FEED = 12
SUMMARY_CHARS = 300  # per entry; keeps the prompt size sane
LOOKBACK_HOURS = 24

TAG_RE = re.compile(r"<[^>]+>")


def clean(html):
    """Strip tags and collapse whitespace — feed summaries arrive as HTML."""
    return " ".join(TAG_RE.sub(" ", html or "").split())


def fresh(entry, cutoff):
    """Keep entries newer than cutoff; undated entries are kept."""
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return True
    return datetime(*stamp[:6], tzinfo=timezone.utc) >= cutoff


def gather_stories():
    """{category: [{title, summary, link}, ...]} — failed feeds skipped."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    out = {}
    for category, urls in FEEDS.items():
        stories = []
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:ENTRIES_PER_FEED]:
                    if not fresh(e, cutoff):
                        continue
                    stories.append(
                        {
                            "title": e.get("title", "(untitled)"),
                            "summary": clean(e.get("summary", ""))[:SUMMARY_CHARS],
                            "link": e.get("link", ""),
                        }
                    )
            except Exception:
                continue  # dead feed → just use the others
        out[category] = stories
    return out


def summarize(stories):
    """One model call: raw feed entries in, sectioned detailed briefing out."""
    blocks = []
    for category, entries in stories.items():
        lines = "\n".join(
            f"- {s['title']} | {s['summary']} | {s['link']}" for s in entries
        )
        blocks.append(
            f"=== {category} candidates ===\n{lines or '(feeds unavailable)'}"
        )

    prompt = (
        "You are composing my detailed daily tech briefing from the last "
        "24h of feed entries below (title | summary | link). Plain text "
        "only — no markdown headers or bold.\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
        "Produce EXACTLY this output structure:\n\n"
        "🤖 AI — models, products, research, AI policy\n\n"
        "💻 SOFTWARE & DEV — releases, frameworks, open source, dev tools\n\n"
        "🔩 HARDWARE — chips, GPUs, devices, components\n\n"
        "🏢 INDUSTRY — big-tech business, acquisitions, major funding, "
        "regulation\n\n"
        "🔐 SECURITY — breaches, vulnerabilities, patches worth acting on\n\n"
        "Rules:\n"
        "- 3–5 stories per section, ranked by importance. Dedupe stories "
        "covered by multiple feeds into one.\n"
        "- Each story: a headline line, then 1–2 sentences of detail — what "
        "actually happened and why it matters — then the link on its own "
        "line.\n"
        "- INDUSTRY has no candidate block of its own: pull business/"
        "acquisition/regulation stories from any category's candidates.\n"
        "- Hacker News entries have no summary — judge by title, include "
        "only clearly significant ones.\n"
        "- Blank line between stories.\n"
        "- A section with nothing notable: one line saying 'quiet day'."
    )
    return ask_llm(prompt, max_tokens=4000)


def main():
    load_dotenv(BASE_DIR / ".env")
    stories = gather_stories()
    scanned = sum(len(v) for v in stories.values())

    header = (
        f"🗞 Tech briefing — {datetime.now(IST):%a %d %b %Y}\n"
        f"(last 24h, {scanned} stories scanned)\n\n"
    )

    if scanned == 0:
        body = "Quiet day: all tech feeds unreachable ☕"
    else:
        body = summarize(stories)

    send_telegram(header + body)


if __name__ == "__main__":
    main()
