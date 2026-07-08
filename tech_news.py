#!/usr/bin/env python3
"""Tech briefing.

One detailed Telegram message every morning (~7:00 IST via GitHub Actions):
the last 24h of tech news across AI, software & dev, hardware, industry and
security — each story summarized with what happened, why it matters, and
a link.

Separate from the 6 AM news briefing: own repo, own bot, own schedule —
it fails and gets fixed independently.

Cross-day memory (state/seen.json, committed back by the workflow): a
story that lingers in the feeds for days is only ever briefed once —
candidate links are remembered for 3 days and filtered out on re-entry.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from dotenv import load_dotenv

from agentlib import ask_llm, send_telegram

BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

STATE_FILE = BASE_DIR / "state" / "seen.json"
SEEN_DAYS = 3  # feeds re-serve stories for a day or two; 3 covers weekends


def load_seen():
    """{link: 'YYYY-MM-DD'} of recently briefed candidates, pruned to window.

    Anything fed to the model counts as seen — a story it chose to skip
    yesterday was not important enough to resurface unchanged today."""
    try:
        seen = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).strftime(
        "%Y-%m-%d"
    )
    return {k: v for k, v in seen.items() if isinstance(v, str) and v >= cutoff}


def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")

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
    "Industry": [
        # Tech business, funding rounds and acquisitions — gives INDUSTRY
        # its own candidates instead of scavenging the other sections.
        "https://techcrunch.com/category/venture/feed/",
    ],
    "Security": [
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.bleepingcomputer.com/feed/",
    ],
}
ENTRIES_PER_FEED = 12
SUMMARY_CHARS = 500  # per entry; keeps the prompt size sane
LOOKBACK_HOURS = 24

TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")

HN_FEED = "https://news.ycombinator.com/rss"


def enrich_hn(stories):
    """Attach points/comments to Hacker News entries via the Algolia API.

    HN's RSS carries titles only, so significance used to be guessed from
    the headline alone. Points and comment counts give the model a real
    signal. Exact title match guards against wrong lookups; any failure
    leaves the entry unenriched — never worth losing a story over."""
    for s in stories:
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": s["title"][:80], "tags": "story", "hitsPerPage": 1},
                timeout=15,
            )
            r.raise_for_status()
            hits = r.json().get("hits", [])
            if hits and hits[0].get("title", "").lower() == s["title"].lower():
                s["summary"] = (
                    f"HN: {hits[0].get('points', 0)} points, "
                    f"{hits[0].get('num_comments', 0)} comments"
                )
        except Exception:
            continue
    return stories


def clean(html):
    """Strip tags and collapse whitespace — feed summaries arrive as HTML."""
    return " ".join(TAG_RE.sub(" ", html or "").split())


def fresh(entry, cutoff):
    """Keep entries newer than cutoff; undated entries are kept."""
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return True
    return datetime(*stamp[:6], tzinfo=timezone.utc) >= cutoff


def gather_stories(seen=frozenset()):
    """{category: [{title, summary, link}, ...]} — failed feeds skipped."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    out = {}
    for category, urls in FEEDS.items():
        stories = []
        for url in urls:
            try:
                feed = feedparser.parse(url)
                batch = []
                for e in feed.entries[:ENTRIES_PER_FEED]:
                    if not fresh(e, cutoff) or e.get("link", "") in seen:
                        continue
                    batch.append(
                        {
                            "title": e.get("title", "(untitled)"),
                            "summary": clean(e.get("summary", ""))[:SUMMARY_CHARS],
                            "link": e.get("link", ""),
                        }
                    )
                if url == HN_FEED:
                    enrich_hn(batch)
                stories += batch
            except Exception:
                continue  # dead feed → just use the others
        out[category] = stories
    return out


def validate_links(text, known_links):
    """Neutralize invented URLs: replace any link the model emitted that is
    not among the gathered story URLs. The model must cite only links we
    actually fetched — a hallucinated URL is worse than none."""

    def check(match):
        url = match.group(0)
        trail = ""
        while url and url[-1] in ").,;'\"":
            trail = url[-1] + trail
            url = url[:-1]
        if url in known_links:
            return match.group(0)
        return "(link unavailable)" + trail

    return URL_RE.sub(check, text)


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
        "- INDUSTRY has its own candidates, but also pull any business/"
        "acquisition/regulation stories surfacing in other categories.\n"
        "- Hacker News entries carry 'HN: N points, M comments' instead of "
        "a summary — use the score to judge significance (roughly: 150+ "
        "notable, 500+ major; below that only if the title is clearly "
        "important).\n"
        "- Blank line between stories.\n"
        "- A section with nothing notable: one line saying 'quiet day'."
    )
    return ask_llm(prompt, max_tokens=4000)


def main():
    load_dotenv(BASE_DIR / ".env")
    seen = load_seen()
    stories = gather_stories(seen)
    scanned = sum(len(v) for v in stories.values())

    header = (
        f"🗞 Tech briefing — {datetime.now(IST):%a %d %b %Y}\n"
        f"(last 24h, {scanned} fresh stories scanned)\n\n"
    )

    known_links = {
        s["link"] for entries in stories.values() for s in entries if s["link"]
    }
    if scanned == 0:
        body = "Quiet day: nothing new since yesterday's briefing ☕"
    else:
        body = validate_links(summarize(stories), known_links)

    send_telegram(header + body)

    # Remember what the model was shown — after the send, so a state
    # failure never costs the briefing itself.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for link in known_links:
        seen[link] = today
    try:
        save_seen(seen)
    except OSError:
        pass


if __name__ == "__main__":
    main()
