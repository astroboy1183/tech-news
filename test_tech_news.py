#!/usr/bin/env python3
"""Offline tests for tech_news — no network, no API keys required."""

import unittest

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
        # A known link followed by a period should still validate.
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


if __name__ == "__main__":
    unittest.main()
