# tech-news

The fleet's flagship: a comprehensive tech briefing → Telegram, two
editions a day via GitHub Actions. One agent, one task, one bot:
`@jayanth_tech_briefing_bot`.

- **~06:59 IST** — the full morning briefing
- **19:15 IST** — a tight *evening wrap* of what broke AFTER the morning
  (the seen-memory guarantees zero overlap); silent unless there's real
  news — or a newly exploited CVE, which never waits

Forty-five verified feeds + three structured APIs (Hacker News/Algolia,
CISA KEV, GitHub search), nine sections plus four deterministic blocks.
**Every bullet is detailed**: 2-3 sentences of what happened (from the
fetched article) plus a `↳` background-context line — prior
developments, why now — drawn from the article, the briefed memory and
well-established facts only.

```
🗞 Tech briefing — Sat 11 Jul
230 fresh stories · 45 feeds + HN/KEV/GitHub

🗞 Top: <the day's biggest tech story>       ← also sent as a PHOTO front
                                               page (the article's own
                                               og:image, captioned)

🤖 AI — 5             (TC AI, VentureBeat AI + PRIMARY sources: OpenAI,
                       DeepMind, Google AI, HuggingFace, MIT Tech Review,
                       Simon Willison)
📊 DATA — 4           (data eng/science/analytics: Towards Data Science,
                       KDnuggets, Data Engineering Weekly, Seattle Data
                       Guy, InfoWorld)
☁️ INFRA — 4          (The New Stack, Kubernetes blog, CNCF, AWS News,
                       GCP, Azure, DevOps.com — the news lens; vendor
                       engineering blogs belong to the eng-blogs agent)
🖥 OS — 4             (Windows: Neowin, WindowsLatest · Linux: Phoronix,
                       OMG Ubuntu, LWN · macOS: 9to5Mac, MacRumors —
                       selector told to mix all three OSes)
💻 SOFTWARE & DEV — 3 (HN, Ars, Lobsters, GitHub blog, InfoQ)
🔩 HARDWARE — 3       (Tom's, Verge, ServeTheHome)
🏢 INDUSTRY — 2       (TC Venture, TC main, The Register)
🇮🇳 INDIA TECH — 2     (Inc42, MediaNama, YourStory)
🔐 SECURITY — 3       (Hacker News/THN, BleepingComputer, Krebs, Schneier)

🔥 HN TOP             top-5 by points in the window, straight from the
                      Algolia API — the community's actual front page,
                      verbatim titles + points/comments + article and
                      discussion links, no model judgment
📈 RISING REPOS       new GitHub repos crossing ★300 this week (search
                      API), never repeated (extras memory)
🚨 PATCH NOW          new entries in CISA's Known Exploited
                      Vulnerabilities catalog — actively exploited in
                      the wild, with NVD links and patch-due dates;
                      appears in BOTH editions
🗓 WEEK IN TECH       Saturday mornings: the week's story arcs traced
                      from the 7-day briefed memory
```

**👁 Watchlist**: the `TECH_WATCH` secret holds comma-separated personal
topics (seeded: `Anthropic, OpenAI, Databricks, Spark, Kafka, Snowflake,
Airflow`). Matching candidates are 👁-marked for the selector,
*deterministically forced into the selection even if the model skips
them* (bounded by `WATCH_EXTRA` per section), and their bullets carry
the 👁 prefix. Change anytime with `gh secret set TECH_WATCH`.

Bullets are written from the ARTICLES, not the headlines — a two-stage
pipeline: a cheap model (`TECH_MODEL_SELECT`, default haiku) picks from
~350 candidates, the code fetches full article text for just those
(boilerplate-stripped, 3k chars; paywalls fall back to the snippet), and
a stronger model (`TECH_MODEL_WRITE`, default sonnet) writes bullets
with version numbers, benchmarks and consequences — each with its
validated source link.

## How the code works

`tech_news.py`, in pipeline order:

- **`FEEDS`** — `{category: [feed urls]}`, 45 sources, every one probed
  for reachability + freshness before inclusion (the header comment
  documents ~13 rejects: Anthropic/Meta AI/Windows blog/9to5Linux
  dead or 403, Thurrott too general, Changelog podcast-only…).
  Data-vendor engineering blogs are deliberately absent — eng-blogs
  owns them; DATA and INFRA here are the news/practitioner lens.
- **`edition(now)`** — morning (full `SECTION_CAPS`, 24h lookback) or
  evening (tight `EVENING_CAPS`, 14h) by IST hour.
- **`hn_window(hours)`** — ONE Algolia call serving two purposes: the
  🔥 HN TOP block (top-5 by points, `HN_MIN_POINTS = 100` floor) and a
  title→(points, comments) map that enriches HN entries in the dev
  section, so significance is measured, not guessed. `[]` on failure —
  the RSS spine still delivers.
- **`kev_block(known)`** — fetches CISA's KEV catalog (keyless JSON,
  ~1600 entries), surfaces entries added in the last 7 days that we
  haven't shown before, capped at 5, each with vendor/product, the
  official short description, patch-due date and its NVD link. Runs in
  BOTH editions. Entirely deterministic — no model touches the one block
  where a wrong detail could hurt.
- **`rising_repos(shown)`** — GitHub search (workflow's own token) for
  repos created this week already past ★300; the extras memory ensures
  a repo is shown exactly once.
- **`gather_stories(seen, lookback, hn_scores)`** — per-feed try/except,
  freshness filter, seen-memory dedupe, watchlist 👁-flagging.
- **`select_stories(...)`** — stage 1 (haiku): picks indices per
  category under editorial rules (one story one category, outlet
  variety, HN score thresholds, skip press-release fluff); skipped 👁
  stories are forced back in by code; unparseable reply falls back to
  first-N.
- **`fetch_article` / `write_briefing`** — stage 2 (sonnet) writes from
  real article text with the edition-aware intro and the `===STATE===`
  JSON tail (`briefed` story keys + `top_link`).
- **`validate_links`** — any URL the model emitted that wasn't among the
  gathered links becomes `(link unavailable)`. The deterministic blocks
  are appended AFTER validation — their URLs are code-fetched, not
  model-emitted.
- **`fetch_og_image` / `send_photo`** — the Top story's own image as a
  captioned photo front page; pure enrichment, text unaffected on any
  failure.
- **`week_in_review`** — Saturday mornings, traces arcs from the 7-day
  briefed memory; `NONE` sentinel when no real arcs exist.
- **`main()`** — edition → HN window → gather → KEV → select → fetch →
  write → validate → assemble (body + 🔥 + 📈 + 🚨 + 🗓) → photo → send →
  save state (AFTER the send, so a state failure never costs the
  message).

## State (committed back by the workflow)

| File | Keeps | Window |
|---|---|---|
| `state/seen.json` | candidate links shown to the model | 3 days |
| `state/briefed.json` | what the bullets actually said | 7 days |
| `state/extras.json` | KEV CVEs + repos already surfaced | 90/60 days |

## Design notes

- The evening wrap exists because tech news breaks on US time — a
  morning-only briefing reads the US-morning cycle a day late. The
  seen-memory makes the wrap new-only by construction.
- 🚨 PATCH NOW is the only block that can break evening silence on its
  own: an actively exploited CVE is exactly the thing that cannot wait.
- The watchlist guarantee is code-enforced (mail-digest VIP pattern).
- HN significance is measured (Algolia points), and 🔥 HN TOP is fully
  deterministic — the model neither picks nor rewrites it.
- Tests run in CI on every push (`.github/workflows/tests.yml`).

## Ops

- Schedule: fleet-scheduler dispatches 06:59 and 19:15 IST sharp; backup
  crons `29 1` / `29 2` / `45 13` / `45 14 * * *` UTC. The dedupe guard
  uses a **3-hour window** so each backup pairs with its own edition.
- Run now: `gh workflow run tech-news.yml -R astroboy1183/tech-news`
- Secrets (Actions): `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `TECH_WATCH` (optional watchlist); the rising-repos
  search uses the workflow's own `github.token`.
- Local test: `cd ~/agents/tech_news && <any fleet venv>/bin/python tech_news.py`
