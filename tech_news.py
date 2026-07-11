#!/usr/bin/env python3
"""Tech briefing — the fleet's flagship.

Two Telegram editions a day via GitHub Actions, from 45 verified feeds
plus three structured APIs (Hacker News/Algolia, CISA KEV, GitHub search):

  morning (6:00 IST)  — the full briefing
  evening (19:15 IST) — a tight wrap of what broke SINCE the morning
                        (seen-memory guarantees zero overlap); silent
                        unless there's real news or a new exploited CVE

Every bullet is DETAILED: what happened (concrete facts from the fetched
article) plus a "↳" background-context line situating the story — prior
developments, why now — drawn from the article, the briefed memory and
well-established facts only, never speculation. The five core topics
(AI, data, infra, OS, hardware) run up to 10 stories deep every
morning; the supporting sections stay tight.

  🗞 Top             — the day's biggest tech story (sent as a photo
                        front page when the article carries an og:image)
  🤖 AI              — models, products, research, policy; primary
                        sources (OpenAI, DeepMind, Google, HuggingFace)
                        next to the trade press
  📊 DATA            — data engineering, data science, analytics: the
                        practitioner press (TDS, KDnuggets, DE Weekly)
  ☁️ INFRA           — cloud platforms, Kubernetes, DevOps, SRE (the
                        NEWS lens; vendor engineering blogs belong to
                        the eng-blogs agent)
  🖥 OS              — Windows, Linux, macOS: releases, features, EOLs,
                        breaking changes
  💻 SOFTWARE & DEV  — releases, frameworks, open source, dev tools
  🔩 HARDWARE        — chips, GPUs, devices, servers
  🏢 INDUSTRY        — big-tech business, funding, acquisitions, regulation
  🇮🇳 INDIA TECH      — the Indian startup/policy scene the US feeds skip
  🔐 SECURITY        — breaches, vulnerabilities, patches worth acting on

  🔥 HN TOP          — deterministic: the community's actual front page,
                        top-5 by points in the window (Algolia API)
  🚨 PATCH NOW       — deterministic tripwire: new entries in CISA's
                        Known Exploited Vulnerabilities catalog — if it's
                        here, someone is exploiting it in the wild NOW
  🗓 WEEK IN TECH    — Saturday mornings: the week's story arcs traced
                        from the briefed memory

Bullets are written from the ARTICLES, not the headlines (two-stage
select/fetch/write), each with its source link validated against the
gathered set. TECH_WATCH (comma-separated topics, from a secret) is a
personal watchlist: matching stories are always selected and 👁-flagged.

Three memories (state/, committed back by the workflow):
  seen.json    — candidate links shown to the model, 3 days
  briefed.json — what the bullets actually SAID, 7 days
  extras.json  — KEV CVEs already surfaced, so the tripwire never
                 repeats itself

(Rising GitHub repos moved to the repo-review agent — repos are its
beat; one agent, one task.)

Hard failures raise and land in the Actions log; the deterministic
blocks are enrichments and can never sink the briefing.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
from dotenv import load_dotenv

from agentlib import ask_llm, send_telegram

BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

# category → feeds. Every URL verified before inclusion (probe sweeps
# 11 Jul 2026). Tested and REJECTED: Anthropic + Meta AI + Entrackr +
# Register/databases + Windows Central + Analytics India Mag (404/empty),
# Windows blog + 9to5Linux (403), Datanami + BigDATAwire (dead domains),
# VentureBeat/data (empty), Changelog (podcast feed), Thurrott (too much
# general-media filler). Data-vendor engineering blogs (Databricks,
# Snowflake, dbt, Confluent, DuckDB, AWS Big Data) are deliberately
# ABSENT — the eng-blogs agent already covers them; DATA and INFRA here
# are the news/practitioner lens, not the vendor-blog lens.
FEEDS = {
    "ai": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://venturebeat.com/category/ai/feed/",
        "https://openai.com/news/rss.xml",
        "https://deepmind.google/blog/rss.xml",
        "https://blog.google/technology/ai/rss/",
        "https://huggingface.co/blog/feed.xml",
        "https://www.technologyreview.com/feed/",
        "https://simonwillison.net/atom/everything/",
    ],
    "data": [
        "https://towardsdatascience.com/feed",
        "https://www.kdnuggets.com/feed",
        "https://www.dataengineeringweekly.com/feed",
        "https://seattledataguy.substack.com/feed",
        "https://www.infoworld.com/feed/",
    ],
    "infra": [
        "https://thenewstack.io/feed/",
        "https://kubernetes.io/feed.xml",
        "https://www.cncf.io/feed/",
        "https://aws.amazon.com/blogs/aws/feed/",
        "https://cloudblog.withgoogle.com/rss/",
        "https://azure.microsoft.com/en-us/blog/feed/",
        "https://devops.com/feed/",
    ],
    "os": [
        # Windows
        "https://www.neowin.net/news/rss/",
        "https://www.windowslatest.com/feed/",
        # Linux
        "https://www.phoronix.com/rss.php",
        "https://www.omgubuntu.co.uk/feed",
        "https://lwn.net/headlines/rss",
        # macOS
        "https://9to5mac.com/feed/",
        "https://feeds.macrumors.com/MacRumors-All",
    ],
    "dev": [
        "https://news.ycombinator.com/rss",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://lobste.rs/rss",
        "https://github.blog/feed/",
        "https://feeds.feedburner.com/InfoQ",
    ],
    "hardware": [
        "https://www.tomshardware.com/feeds/all",
        "https://www.theverge.com/rss/index.xml",
        "https://www.servethehome.com/feed/",
    ],
    "industry": [
        "https://techcrunch.com/category/venture/feed/",
        "https://techcrunch.com/feed/",
        "https://www.theregister.com/headlines.atom",
    ],
    "india": [
        "https://inc42.com/feed/",
        "https://www.medianama.com/feed/",
        "https://yourstory.com/feed",
    ],
    "security": [
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.bleepingcomputer.com/feed/",
        "https://krebsonsecurity.com/feed/",
        "https://www.schneier.com/feed/atom/",
    ],
}
ENTRIES_PER_FEED = 10
SNIPPET_CHARS = 250
LOOKBACK_HOURS = 24
EVENING_LOOKBACK_HOURS = 14  # 6:00 → 19:15 plus margin; seen-memory
                             # already blocks what the morning carried

# Two-stage bullets: a cheap model SELECTS from ~450 candidates, the code
# fetches full articles for just the chosen few, a stronger model WRITES
# from real article text. The five core topics run DEEP — up to 10
# stories each; the supporting sections stay tight so the briefing has
# depth where it matters without drowning the rest.
SECTION_CAPS = {  # morning, the full briefing
    "ai": 10, "data": 10, "infra": 10, "os": 10, "hardware": 10,
    "dev": 3, "industry": 2, "india": 2, "security": 3,
}
EVENING_CAPS = {  # the wrap stays tighter — Top + ~14 bullets
    "ai": 3, "data": 2, "infra": 2, "os": 2, "hardware": 1,
    "dev": 1, "industry": 1, "india": 1, "security": 1,
}
WATCH_EXTRA = 2        # watchlist stories forced in per section, at most
ARTICLE_CHARS = 3000
FETCH_TIMEOUT = 15
FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (tech-news briefing)"}

# Deterministic blocks
HN_FEED = "https://news.ycombinator.com/rss"
HN_API = "https://hn.algolia.com/api/v1/search"
HN_TOP_COUNT = 5       # front-page lines in 🔥 HN TOP
HN_MIN_POINTS = 100    # below this the community hasn't voted it up yet
KEV_URL = ("https://www.cisa.gov/sites/default/files/feeds/"
           "known_exploited_vulnerabilities.json")
KEV_WINDOW_DAYS = 7    # only recently added CVEs are news
KEV_CAP = 5
KEV_KEEP_DAYS = 90     # prune remembered CVEs after this

TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")

STATE_DIR = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "seen.json"
BRIEFED_FILE = STATE_DIR / "briefed.json"
EXTRAS_FILE = STATE_DIR / "extras.json"
SEEN_DAYS = 3     # feeds re-serve stories for a day or two
BRIEFED_DAYS = 7  # a week of "what the bullets said" — Saturday traces arcs
STATE_MARKER = "===STATE==="


def edition(now):
    """morning (the full briefing) or evening (the wrap), by IST hour."""
    return "morning" if now.hour < 12 else "evening"


def watch_terms():
    """Personal watchlist from TECH_WATCH (comma-separated, case-blind)."""
    raw = os.environ.get("TECH_WATCH", "")
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def watch_hit(entry, terms):
    """Does this candidate mention a watchlist topic? Title + snippet."""
    hay = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(t in hay for t in terms)


def clean(html):
    """Strip tags and collapse whitespace — feed summaries arrive as HTML."""
    return " ".join(TAG_RE.sub(" ", html or "").split())


def fresh(entry, cutoff):
    """Keep entries newer than cutoff; undated entries are kept."""
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return True
    return datetime(*stamp[:6], tzinfo=timezone.utc) >= cutoff


def load_seen():
    """{link: 'YYYY-MM-DD'} of recently briefed candidates, pruned to window.

    Anything fed to the model counts as seen — a story it chose to skip
    yesterday was not important enough to resurface unchanged today. The
    same memory makes the evening wrap new-only: the morning run saved
    every candidate it gathered."""
    try:
        seen = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).strftime(
        "%Y-%m-%d"
    )
    return {k: v for k, v in seen.items() if isinstance(v, str) and v >= cutoff}


def save_seen(seen):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True) + "\n")


def load_briefed():
    """{date: [story keys]} — what recent bullets actually said, pruned."""
    try:
        briefed = json.loads(BRIEFED_FILE.read_text())
    except (OSError, ValueError):
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=BRIEFED_DAYS)).strftime(
        "%Y-%m-%d"
    )
    return {
        d: [s for s in lines if isinstance(s, str)]
        for d, lines in briefed.items()
        if isinstance(d, str) and d >= cutoff and isinstance(lines, list)
    }


def save_briefed(briefed):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFED_FILE.write_text(json.dumps(briefed, indent=1, sort_keys=True) + "\n")


def load_extras():
    """{"kev": {cveID: dateAdded}} — what the tripwire already surfaced,
    pruned to its window."""
    try:
        extras = json.loads(EXTRAS_FILE.read_text())
    except (OSError, ValueError):
        extras = {}
    kev_cut = (
        datetime.now(timezone.utc) - timedelta(days=KEV_KEEP_DAYS)
    ).strftime("%Y-%m-%d")
    kev = extras.get("kev", {})
    return {
        "kev": {k: v for k, v in kev.items()
                if isinstance(v, str) and v >= kev_cut},
    }


def save_extras(extras):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXTRAS_FILE.write_text(json.dumps(extras, indent=1, sort_keys=True) + "\n")


def split_state(reply):
    """(message text, today's briefed keys, top-story link) from the reply.

    The model appends a JSON tail after STATE_MARKER; a malformed tail
    costs the continuity memory and the photo, never the briefing."""
    if STATE_MARKER not in reply:
        return reply.strip(), [], ""
    text, _, tail = reply.partition(STATE_MARKER)
    start, end = tail.find("{"), tail.rfind("}")
    keys, top_link = [], ""
    if start != -1 and end > start:
        try:
            state = json.loads(tail[start : end + 1])
            keys = state.get("briefed", [])
            top_link = state.get("top_link", "")
        except (ValueError, AttributeError):
            keys, top_link = [], ""
    if not isinstance(top_link, str):
        top_link = ""
    return text.strip(), [k for k in keys if isinstance(k, str)], top_link


def hn_window(hours=24):
    """Top HN stories of the window via Algolia, points-sorted.

    One API call serves two purposes: the 🔥 HN TOP block and the
    points/comments enrichment for HN entries in the dev section.
    [] on any failure — the RSS spine still delivers."""
    try:
        since = int(time.time()) - hours * 3600
        r = requests.get(
            HN_API,
            params={
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>50",
                "hitsPerPage": 100,
            },
            timeout=FETCH_TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            if not h.get("title"):
                continue
            item = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
            out.append(
                {
                    "title": h["title"],
                    "points": h.get("points") or 0,
                    "comments": h.get("num_comments") or 0,
                    "url": h.get("url") or item,  # Ask/Show HN have no url
                    "item": item,
                }
            )
        return sorted(out, key=lambda s: -s["points"])
    except Exception:
        return []


def hn_block(top):
    """🔥 HN TOP — the community's actual front page, no model judgment."""
    picks = [s for s in top if s["points"] >= HN_MIN_POINTS][:HN_TOP_COUNT]
    if not picks:
        return ""
    lines = ["🔥 HN TOP"]
    for s in picks:
        lines.append(f"• {s['title']} — {s['points']}↑ {s['comments']}💬")
        link = s["url"] if s["url"] == s["item"] else f"{s['url']} · {s['item']}"
        lines.append(f"  {link}")
    return "\n".join(lines)


def kev_block(known):
    """🚨 PATCH NOW from CISA's Known Exploited Vulnerabilities catalog.

    Deterministic tripwire: entries added in the last KEV_WINDOW_DAYS that
    we have not surfaced before. Returns (block text, {cveID: dateAdded}
    of the newly shown ones). ('' , {}) when quiet or unreachable —
    accuracy matters most here, so no model touches this block."""
    try:
        r = requests.get(KEV_URL, timeout=30, headers=FETCH_HEADERS)
        r.raise_for_status()
        vulns = r.json().get("vulnerabilities", [])
    except Exception:
        return "", {}
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=KEV_WINDOW_DAYS)
    ).strftime("%Y-%m-%d")
    new = sorted(
        (
            v
            for v in vulns
            if v.get("cveID")
            and v.get("dateAdded", "") >= cutoff
            and v["cveID"] not in known
        ),
        key=lambda v: v.get("dateAdded", ""),
        reverse=True,
    )[:KEV_CAP]
    if not new:
        return "", {}
    lines = ["🚨 PATCH NOW — added to CISA's exploited-in-the-wild list"]
    for v in new:
        what = f"{v.get('vendorProject', '?')} {v.get('product', '?')}".strip()
        due = f" · patch due {v['dueDate']}" if v.get("dueDate") else ""
        lines.append(f"• {v['cveID']} — {what}{due}")
        desc = " ".join((v.get("shortDescription") or "").split())
        if desc:
            lines.append(f"  {desc[:160]}")
        lines.append(f"  https://nvd.nist.gov/vuln/detail/{v['cveID']}")
    return "\n".join(lines), {v["cveID"]: v.get("dateAdded", "") for v in new}


def gather_stories(seen=frozenset(), lookback=LOOKBACK_HOURS, hn_scores=None):
    """{category: [{title, summary, link}, ...]} — failed feeds skipped.

    HN entries carry 'HN: N points, M comments' as their summary when the
    Algolia window (hn_scores: lowercase title → (points, comments))
    knows them — significance measured, not guessed."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)
    hn_scores = hn_scores or {}
    out = {}
    for category, urls in FEEDS.items():
        stories = []
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:ENTRIES_PER_FEED]:
                    if not e.get("title") or not fresh(e, cutoff):
                        continue
                    if e.get("link", "") in seen:
                        continue
                    summary = clean(e.get("summary", ""))[:SNIPPET_CHARS]
                    if url == HN_FEED:
                        pts = hn_scores.get(e["title"].lower())
                        summary = (
                            f"HN: {pts[0]} points, {pts[1]} comments"
                            if pts
                            else ""
                        )
                    stories.append(
                        {
                            "title": e["title"],
                            "summary": summary,
                            "link": e.get("link", ""),
                        }
                    )
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


def select_stories(stories, briefed, model, caps):
    """Stage 1: a cheap model picks which stories deserve the bullets.

    Returns {category: [entries]} capped per ``caps``. Watchlist (👁)
    candidates the model skipped are forced back in — bounded by
    WATCH_EXTRA so one broad term can't flood a section. An unparseable
    reply falls back to the first N candidates per section."""
    blocks = []
    for category, entries in stories.items():
        lines = "\n".join(
            f"{i}. {'👁 ' if e.get('watch') else ''}{e['title']}"
            f"{' | ' + e['summary'] if e['summary'] else ''}"
            for i, e in enumerate(entries)
        )
        blocks.append(f"=== {category} ===\n{lines or '(none)'}")
    recently = [key for lines in briefed.values() for key in lines]

    reply = ask_llm(
        "You are selecting stories for my daily tech briefing. I am a "
        "data & AI engineer in Hyderabad — model releases, data "
        "platforms, developer tooling and the India-US tech corridor all "
        "matter to me.\n\n"
        + "\n\n".join(blocks)
        + "\n\n=== RECENTLY BRIEFED (already covered) ===\n"
        + ("\n".join(f"- {k}" for k in recently) or "(none)")
        + "\n\nPick per category, by candidate index: "
        + ", ".join(f"{s} up to {n}" for s, n in caps.items())
        + ". Rules:\n"
        "- 👁 marks my personal watchlist — ALWAYS select 👁 candidates.\n"
        "- Several feeds carrying the same story = importance signal; "
        "keep exactly one copy, from the best source, in ONE category "
        "only (if it fits several, pick the best fit).\n"
        "- Vary outlets within a category — one outlet must not fill it.\n"
        "- 'HN: N points' entries: judge by score — 150+ notable, 500+ "
        "major; unscored HN titles only if clearly important.\n"
        "- data = data engineering, data science, analytics — pipelines, "
        "warehouses, ML ops, BI; prefer stories with technique or tooling "
        "substance over listicles.\n"
        "- infra = cloud platforms, Kubernetes, DevOps, SRE, networking.\n"
        "- os = Windows, Linux and macOS — releases, features, EOLs, "
        "breaking changes; prefer a MIX across the three OSes when "
        "candidates allow, and skip pure consumer-gadget chatter.\n"
        "- dev = languages, frameworks, releases, tooling.\n"
        "- india = Indian startup/policy/tech-business news with "
        "substance; skip press-release fluff.\n"
        "- security = what a practitioner should KNOW or ACT on; skip "
        "commodity malware churn.\n"
        "- Skip stories already briefed UNLESS a candidate carries a "
        "genuine development.\n\n"
        "Output ONLY one JSON object mapping category name to an array "
        'of chosen indices, e.g. {"ai": [0, 4], "dev": [2]}. No prose.',
        max_tokens=900,
        model=model,
    )
    try:
        start, end = reply.find("{"), reply.rfind("}")
        picks = json.loads(reply[start : end + 1])
        selected = {}
        for category, entries in stories.items():
            idx = [
                i
                for i in picks.get(category, [])
                if isinstance(i, int) and 0 <= i < len(entries)
            ]
            chosen = [entries[i] for i in idx[: caps[category]]]
            # deterministic watchlist guarantee, model-proof
            forced = [e for e in entries if e.get("watch") and e not in chosen]
            selected[category] = chosen + forced[:WATCH_EXTRA]
        return selected
    except (ValueError, AttributeError, TypeError):
        return {s: entries[: caps[s]] for s, entries in stories.items()}


def fetch_article(link):
    """Readable text of a story page, tags stripped — '' on any failure.

    Snippets can't carry benchmarks, version numbers and consequences;
    the article can. Paywalled/blocking sites fall back to the snippet."""
    try:
        resp = requests.get(link, timeout=FETCH_TIMEOUT, headers=FETCH_HEADERS)
        resp.raise_for_status()
        html = re.sub(
            r"(?is)<(script|style|head|nav|footer|header|aside)[^>]*>.*?</\1>",
            " ",
            resp.text,
        )
        text = re.sub(r"<[^>]+>", " ", html)
        return " ".join(text.split())[:ARTICLE_CHARS]
    except Exception:
        return ""


def fetch_og_image(link):
    """The page's og:image URL — the story's own front-page photo.

    '' on any failure; the photo is an enrichment, never a dependency."""
    try:
        resp = requests.get(link, timeout=FETCH_TIMEOUT, headers=FETCH_HEADERS)
        resp.raise_for_status()
        meta = re.search(
            r"<meta[^>]+(?:property|name)=[\"']og:image[\"'][^>]*>",
            resp.text[:120_000],
            re.I,
        )
        if not meta:
            return ""
        content = re.search(r"content=[\"']([^\"']+)[\"']", meta.group(0), re.I)
        url = (content.group(1) if content else "").strip()
        return url if url.startswith("http") else ""
    except Exception:
        return ""


def send_photo(photo_url, caption):
    """Front page: the Top story as a Telegram photo. Best-effort — False
    on any failure, and the text briefing (which repeats the Top line)
    goes out regardless, so a broken image costs nothing."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat and photo_url):
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat, "photo": photo_url,
                  "caption": caption[:1000]},
            timeout=FETCH_TIMEOUT,
        )
        return bool(resp.json().get("ok"))
    except Exception:
        return False


def write_briefing(selected, briefed, model, caps, ed="morning"):
    """Stage 2: a stronger model writes the bullets from full article text."""
    blocks = []
    for category, entries in selected.items():
        lines = []
        for e in entries:
            body = e.get("article") or e.get("summary") or "(title only)"
            flag = "👁 " if e.get("watch") else ""
            lines.append(f"- {flag}{e['title']}\n  TEXT: {body}\n  LINK: {e['link']}")
        blocks.append(
            f"=== {category.upper()} — write up to {caps[category]} "
            f"bullets ===\n" + ("\n".join(lines) or "(feeds unavailable)")
        )
    recently = [key for lines in briefed.values() for key in lines]

    intro = (
        "You are composing my daily tech briefing"
        if ed == "morning"
        else "You are composing my EVENING TECH WRAP — a tight update of "
        "what broke after this morning's briefing (everything below is "
        "new since then)"
    )
    prompt = (
        f"{intro} from pre-selected stories, each with article text where "
        "it could be fetched. I am a data & AI engineer in Hyderabad. Be "
        "detailed and substantive — version numbers, benchmarks, prices, "
        "names — never padded. Plain text only — no markdown headers or "
        "bold.\n\n"
        + "\n\n".join(blocks)
        + "\n\n=== RECENTLY BRIEFED (last days — already covered) ===\n"
        + ("\n".join(f"- {k}" for k in recently) or "(none)")
        + "\n\nProduce EXACTLY this output structure (DEV input becomes "
        "the 💻 section, INDIA becomes 🇮🇳):\n\n"
        "🗞 Top: <the single biggest tech story, one line — broadest "
        "consequence for working engineers wins>\n\n"
        "🤖 AI\n📊 DATA\n☁️ INFRA\n🖥 OS\n💻 SOFTWARE & DEV\n🔩 HARDWARE\n"
        "🏢 INDUSTRY\n🇮🇳 INDIA TECH\n🔐 SECURITY\n\n"
        "Rules:\n"
        "- Each bullet: a headline line, then 2-3 sentences of real "
        "substance drawn from TEXT — what actually happened, with the "
        "concrete facts (versions, benchmarks, prices, names) and why it "
        "matters to a practitioner.\n"
        "- Then a background-context line starting with '↳ ': 1-2 "
        "sentences situating the story — what led to it, prior "
        "developments (use RECENTLY BRIEFED where a story continues), "
        "how it fits the larger picture. ONLY well-established "
        "background — no speculation; if you have no real context, omit "
        "the ↳ line entirely rather than pad.\n"
        "- Then the story's LINK on its own line. Where TEXT is missing, "
        "stay conservative: report the headline fact, never invent "
        "detail.\n"
        "- Start bullets for stories marked 👁 with 👁 — they hit my "
        "personal watchlist.\n"
        "- OMIT any section whose input is empty — no placeholder lines.\n"
        "- If a story develops something in RECENTLY BRIEFED, lead with "
        "what is NEW, never re-explain from scratch.\n"
        "- Copy links verbatim — never invent one.\n"
        "- Blank line between stories.\n\n"
        f"Then output the line {STATE_MARKER} and ONE JSON object: "
        '{"briefed": [a terse story key for each bullet you wrote, e.g. '
        '"Gemini 3 Pro launch", "Postgres 19 released"], '
        '"top_link": the LINK of the story your Top line describes}. '
        "No text after the JSON."
    )
    return ask_llm(prompt, max_tokens=16000, model=model)


def week_in_review(briefed, model):
    """Saturday's 🗓 WEEK IN TECH: the week's story arcs, traced from what
    the briefings actually said. Needs 3+ days of memory; '' otherwise."""
    days = {d: keys for d, keys in sorted(briefed.items()) if keys}
    if len(days) < 3:
        return ""
    history = "\n".join(f"{d}: " + "; ".join(keys) for d, keys in days.items())
    reply = ask_llm(
        "Below are the story keys my tech briefings covered each day this "
        "week, oldest first:\n\n"
        + history
        + "\n\nWrite a '🗓 WEEK IN TECH' section: up to 5 bullets, each "
        "tracing ONE story's arc across the week (e.g. '• Gemini 3: "
        "launched Mon, benchmarks contested Wed, enterprise rollout "
        "Fri'), most consequential first. Only connect what these keys "
        "support — NEVER invent developments beyond them. A story "
        "appearing once with no follow-up is not an arc. Plain text, no "
        "links, no commentary. If fewer than 2 real arcs exist, output "
        "exactly: NONE",
        max_tokens=600,
        model=model,
    ).strip()
    if reply == "NONE" or "🗓" not in reply:
        return ""
    return reply


def main():
    load_dotenv(BASE_DIR / ".env")
    now = datetime.now(IST)
    ed = edition(now)
    caps = SECTION_CAPS if ed == "morning" else EVENING_CAPS
    lookback = LOOKBACK_HOURS if ed == "morning" else EVENING_LOOKBACK_HOURS

    seen = load_seen()
    briefed = load_briefed()
    extras = load_extras()

    # One Algolia call serves the 🔥 block and the dev-section enrichment.
    hn = hn_window(lookback)
    hn_scores = {s["title"].lower(): (s["points"], s["comments"]) for s in hn}

    stories = gather_stories(seen, lookback, hn_scores)
    terms = watch_terms()
    for entries in stories.values():
        for e in entries:
            e["watch"] = watch_hit(e, terms)
    scanned = sum(len(v) for v in stories.values())
    feed_count = sum(len(u) for u in FEEDS.values())
    print(f"{ed} edition: {scanned} fresh candidates from {feed_count} feeds")

    # The patch-now tripwire runs in BOTH editions — an actively exploited
    # CVE is exactly the thing that cannot wait for tomorrow morning.
    kev_text, kev_new = kev_block(extras["kev"])

    if scanned == 0 and not kev_text and ed == "evening":
        print("evening wrap: nothing new since this morning — staying silent")
        return

    label = "" if ed == "morning" else " · evening wrap"
    header = (
        f"🗞 Tech briefing — {now:%a %d %b}{label}\n"
        f"{scanned} fresh stories · {feed_count} feeds + HN/KEV/GitHub"
    )
    select_model = os.environ.get("TECH_MODEL_SELECT") or "claude-haiku-4-5"
    write_model = os.environ.get("TECH_MODEL_WRITE") or "claude-sonnet-5"

    briefed_today, top_link = [], ""
    known_links = {
        s["link"] for entries in stories.values() for s in entries if s["link"]
    }
    if scanned == 0:
        body = "Quiet day: nothing new since yesterday's briefing ☕"
    else:
        selected = select_stories(stories, briefed, select_model, caps)
        for entries in selected.values():
            for e in entries:  # fetch real article text for the chosen few
                e["article"] = fetch_article(e["link"])
        body, briefed_today, top_link = split_state(
            write_briefing(selected, briefed, write_model, caps, ed)
        )
        body = validate_links(body, known_links)
        if top_link not in known_links:
            top_link = ""  # same guarantee as the bullets: no invented URLs

    # Deterministic blocks — code-built, appended after link validation
    # (their URLs are fetched, not model-emitted). Morning gets the full
    # set; the evening wrap carries only the tripwire.
    parts = [body]
    if ed == "morning":
        block = hn_block(hn)
        if block:
            parts.append(block)
    if kev_text:
        parts.append(kev_text)
    if ed == "morning" and now.weekday() == 5:  # Saturday
        try:
            week = week_in_review(briefed, write_model)
        except Exception:
            week = ""  # an enrichment must never sink the briefing
        if week:
            parts.append(week)

    # Front page: the Top story's own photo, captioned with the topline.
    if top_link:
        image = fetch_og_image(top_link)
        top_line = next(
            (l for l in body.splitlines() if l.startswith("🗞")), ""
        )
        if image and top_line:
            ok = send_photo(image, top_line)
            print(f"front-page photo: {'sent' if ok else 'failed (non-fatal)'}")

    send_telegram(header + "\n\n" + "\n\n".join(p for p in parts if p))

    # Remember what was shown — after the send, so a state failure never
    # costs the briefing itself.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for link in known_links:
        seen[link] = today
    if briefed_today:
        briefed.setdefault(today, [])
        briefed[today] += briefed_today
    extras["kev"].update(kev_new)
    try:
        save_seen(seen)
        save_briefed(briefed)
        save_extras(extras)
    except OSError:
        pass


if __name__ == "__main__":
    main()
