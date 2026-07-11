#!/usr/bin/env python3
"""Offline tests for tech_news — no network, no API keys required.

Covers link validation, the state-tail parser, editions, the watchlist
guarantee, the deterministic HN/KEV/repos blocks (stubbed network), the
photo helpers and the week-in-review gate."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import tech_news as tn
from tech_news import validate_links


class ValidateLinksTest(unittest.TestCase):
    def test_known_link_kept(self):
        known = {"https://example.com/a"}
        text = "Headline\nhttps://example.com/a"
        self.assertEqual(validate_links(text, known), text)

    def test_invented_link_replaced(self):
        known = {"https://example.com/a"}
        text = "Headline\nhttps://evil.example/made-up"
        out = validate_links(text, known)
        self.assertNotIn("evil.example", out)
        self.assertIn("(link unavailable)", out)

    def test_trailing_punctuation_ignored(self):
        known = {"https://example.com/a"}
        text = "See (https://example.com/a)."
        out = validate_links(text, known)
        self.assertIn("https://example.com/a", out)
        self.assertNotIn("(link unavailable)", out)

    def test_mixed_known_and_invented(self):
        known = {"https://good.example/1", "https://good.example/2"}
        text = (
            "Story one\nhttps://good.example/1\n\n"
            "Story two\nhttps://fake.example/x\n\n"
            "Story three\nhttps://good.example/2"
        )
        out = validate_links(text, known)
        self.assertIn("https://good.example/1", out)
        self.assertIn("https://good.example/2", out)
        self.assertNotIn("fake.example", out)
        self.assertEqual(out.count("(link unavailable)"), 1)

    def test_no_links(self):
        self.assertEqual(validate_links("quiet day", set()), "quiet day")


class SplitStateTest(unittest.TestCase):
    def test_extracts_text_keys_and_top_link(self):
        reply = ('the briefing\n===STATE===\n'
                 '{"briefed": ["k1", "k2"], "top_link": "https://x/top"}')
        text, keys, top = tn.split_state(reply)
        self.assertEqual((text, keys, top),
                         ("the briefing", ["k1", "k2"], "https://x/top"))

    def test_missing_tail_costs_memory_not_message(self):
        self.assertEqual(tn.split_state("no tail"), ("no tail", [], ""))

    def test_garbage_tail_costs_memory_not_message(self):
        self.assertEqual(tn.split_state("msg\n===STATE===\nnope"),
                         ("msg", [], ""))

    def test_non_string_top_link_discarded(self):
        _, _, top = tn.split_state('m\n===STATE===\n{"briefed": [], "top_link": 5}')
        self.assertEqual(top, "")


class EditionTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(tn.edition(datetime(2026, 7, 11, 6, 59, tzinfo=tn.IST)),
                         "morning")
        self.assertEqual(tn.edition(datetime(2026, 7, 11, 19, 15, tzinfo=tn.IST)),
                         "evening")

    def test_caps_cover_all_sections(self):
        self.assertEqual(set(tn.SECTION_CAPS), set(tn.FEEDS))
        self.assertEqual(set(tn.EVENING_CAPS), set(tn.FEEDS))
        self.assertLess(sum(tn.EVENING_CAPS.values()),
                        sum(tn.SECTION_CAPS.values()))


class WatchlistTest(unittest.TestCase):
    def test_terms_parsed(self):
        with mock.patch.dict("os.environ", {"TECH_WATCH": "Kafka, , Spark "}):
            self.assertEqual(tn.watch_terms(), ["kafka", "spark"])

    def test_hit_on_title_and_summary(self):
        self.assertTrue(tn.watch_hit({"title": "Kafka 5.0", "summary": ""},
                                     ["kafka"]))
        self.assertTrue(tn.watch_hit({"title": "x", "summary": "uses Spark"},
                                     ["spark"]))
        self.assertFalse(tn.watch_hit({"title": "x", "summary": "y"}, []))

    def test_skipped_watch_story_forced_in(self):
        stories = {"ai": [
            {"title": f"S{i}", "summary": "", "link": f"https://x/{i}",
             "watch": i == 3}
            for i in range(4)
        ]}
        with mock.patch.object(tn, "ask_llm", return_value='{"ai": [0, 1]}'):
            picked = tn.select_stories(stories, {}, "m", {"ai": 2})
        self.assertEqual([e["title"] for e in picked["ai"]],
                         ["S0", "S1", "S3"])

    def test_unparseable_selector_falls_back(self):
        stories = {"ai": [
            {"title": f"S{i}", "summary": "", "link": f"https://x/{i}"}
            for i in range(4)
        ]}
        with mock.patch.object(tn, "ask_llm", return_value="no json"):
            picked = tn.select_stories(stories, {}, "m", {"ai": 2})
        self.assertEqual(len(picked["ai"]), 2)


class HnBlockTest(unittest.TestCase):
    def _story(self, points, title="T", url="https://a/x", item="https://hn/1"):
        return {"title": title, "points": points, "comments": 7,
                "url": url, "item": item}

    def test_low_scores_filtered_and_capped(self):
        top = [self._story(p) for p in (900, 800, 700, 600, 500, 400, 50)]
        block = tn.hn_block(top)
        self.assertEqual(block.count("• "), tn.HN_TOP_COUNT)
        self.assertNotIn("50↑", block)

    def test_ask_hn_single_link(self):
        # url == item (no external article) must not print the link twice
        block = tn.hn_block([self._story(300, url="https://hn/1")])
        self.assertEqual(block.count("https://hn/1"), 1)

    def test_empty_when_quiet(self):
        self.assertEqual(tn.hn_block([self._story(80)]), "")


def _resp(payload):
    return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)


class KevBlockTest(unittest.TestCase):
    def _vuln(self, cve, added, vendor="Acme", product="Widget"):
        return {"cveID": cve, "dateAdded": added, "vendorProject": vendor,
                "product": product, "shortDescription": "bad bug",
                "dueDate": "2026-08-01"}

    def test_new_recent_cves_surface_once(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payload = {"vulnerabilities": [
            self._vuln("CVE-1", today),
            self._vuln("CVE-2", "2020-01-01"),      # outside window
        ]}
        with mock.patch.object(tn.requests, "get", return_value=_resp(payload)):
            text, new = tn.kev_block(known={})
        self.assertIn("CVE-1", text)
        self.assertNotIn("CVE-2", text)
        self.assertIn("nvd.nist.gov/vuln/detail/CVE-1", text)
        self.assertEqual(new, {"CVE-1": today})

    def test_known_cves_stay_quiet(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payload = {"vulnerabilities": [self._vuln("CVE-1", today)]}
        with mock.patch.object(tn.requests, "get", return_value=_resp(payload)):
            text, new = tn.kev_block(known={"CVE-1": today})
        self.assertEqual((text, new), ("", {}))

    def test_unreachable_catalog_is_quiet_never_fatal(self):
        with mock.patch.object(tn.requests, "get",
                               side_effect=OSError("down")):
            self.assertEqual(tn.kev_block({}), ("", {}))


class RisingReposTest(unittest.TestCase):
    def _repo(self, name, stars=500):
        return {"full_name": name, "stargazers_count": stars,
                "description": "d", "html_url": f"https://github.com/{name}"}

    def test_new_repos_shown_shown_repos_skipped(self):
        payload = {"items": [self._repo("a/one"), self._repo("b/two")]}
        with mock.patch.object(tn.requests, "get", return_value=_resp(payload)):
            text, new = tn.rising_repos(shown={"a/one": "2026-07-10"})
        self.assertNotIn("a/one", text)
        self.assertIn("b/two", text)
        self.assertEqual(list(new), ["b/two"])

    def test_api_failure_is_quiet(self):
        with mock.patch.object(tn.requests, "get", side_effect=OSError("x")):
            self.assertEqual(tn.rising_repos({}), ("", {}))


class ExtrasMemoryTest(unittest.TestCase):
    def test_prunes_old_entries(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as tmp:
            saved_dir, saved_file = tn.STATE_DIR, tn.EXTRAS_FILE
            tn.STATE_DIR = Path(tmp)
            tn.EXTRAS_FILE = Path(tmp) / "extras.json"
            try:
                tn.save_extras({"kev": {"CVE-N": today, "CVE-O": "2020-01-01"},
                                "repos": {"a/b": today, "c/d": "2020-01-01"}})
                extras = tn.load_extras()
            finally:
                tn.STATE_DIR, tn.EXTRAS_FILE = saved_dir, saved_file
        self.assertEqual(list(extras["kev"]), ["CVE-N"])
        self.assertEqual(list(extras["repos"]), ["a/b"])


class PhotoTest(unittest.TestCase):
    def _page(self, html):
        return SimpleNamespace(text=html, raise_for_status=lambda: None)

    def test_og_image_both_attribute_orders(self):
        for html in ('<meta property="og:image" content="https://i/x.jpg"/>',
                     '<meta content="https://i/x.jpg" property="og:image">'):
            with mock.patch.object(tn.requests, "get",
                                   return_value=self._page(html)):
                self.assertEqual(tn.fetch_og_image("https://a"),
                                 "https://i/x.jpg")

    def test_missing_or_failed_is_empty(self):
        with mock.patch.object(tn.requests, "get",
                               return_value=self._page("<html/>")):
            self.assertEqual(tn.fetch_og_image("https://a"), "")
        with mock.patch.object(tn.requests, "get", side_effect=OSError("x")):
            self.assertEqual(tn.fetch_og_image("https://a"), "")

    def test_send_photo_without_credentials_is_noop(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(tn.send_photo("https://i/x.jpg", "cap"))


class WeekInReviewTest(unittest.TestCase):
    WEEK = {f"2026-07-{d:02d}": [f"story {d}"] for d in range(6, 11)}

    def test_needs_three_days(self):
        self.assertEqual(
            tn.week_in_review({"2026-07-10": ["a"], "2026-07-11": ["b"]}, "m"),
            "")

    def test_arcs_returned_none_and_malformed_dropped(self):
        with mock.patch.object(tn, "ask_llm",
                               return_value="🗓 WEEK IN TECH\n• arc"):
            self.assertTrue(tn.week_in_review(self.WEEK, "m").startswith("🗓"))
        with mock.patch.object(tn, "ask_llm", return_value="NONE"):
            self.assertEqual(tn.week_in_review(self.WEEK, "m"), "")
        with mock.patch.object(tn, "ask_llm", return_value="chatty prose"):
            self.assertEqual(tn.week_in_review(self.WEEK, "m"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
