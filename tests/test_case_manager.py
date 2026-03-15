"""
Tests for case_manager.py — case listing, loading, validation.
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

from case_manager import CaseManager

CASES_DIR = os.path.join(os.path.dirname(__file__), '..', 'cases')


class TestCaseManager(unittest.TestCase):

    def setUp(self):
        self.cm = CaseManager(CASES_DIR)

    def test_list_cases_returns_all(self):
        cases = self.cm.list_cases()
        self.assertGreaterEqual(len(cases), 6)
        names = [c["slug"] for c in cases]
        self.assertIn("riverside-robbery", names)
        self.assertIn("biker-bar-murder", names)
        self.assertIn("jewelry-heist", names)
        self.assertIn("stolen-photos", names)

    def test_list_cases_filter_difficulty(self):
        beginners = self.cm.list_cases(difficulty="beginner")
        for c in beginners:
            self.assertEqual(c["difficulty"], "beginner")

    def test_list_cases_filter_tag(self):
        murder_cases = self.cm.list_cases(tag="murder")
        for c in murder_cases:
            self.assertIn("murder", c["tags"])

    def test_load_case(self):
        data = self.cm.load_case("riverside-robbery")
        self.assertEqual(data["case"]["name"], "The Riverside Robbery")
        self.assertIn("evidence", data)

    def test_load_case_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.cm.load_case("nonexistent-case")

    def test_validate_all_cases(self):
        results = self.cm.validate_all_cases()
        self.assertGreaterEqual(len(results), 6)
        for r in results:
            self.assertTrue(r["is_valid"], f"{r['filename']} failed: {r['message']}")

    def test_validate_single_case(self):
        ok, msg = self.cm.validate_case("riverside-robbery")
        self.assertTrue(ok, msg)

    def test_case_has_required_new_fields(self):
        """Verify migrated cases have the new schema fields."""
        data = self.cm.load_case("riverside-robbery")
        self.assertIn("meta", data)
        self.assertIn("difficulty", data["meta"])
        self.assertIn("summary", data["case"])
        self.assertIn("odds_description", data["prior"])
        self.assertIn("odds_numeric", data["prior"])

        for ev in data["evidence"]:
            self.assertIn("summary", ev)
            self.assertIn("guidance", ev)
            self.assertIn("guilty_prompt", ev["guidance"])
            self.assertIn("innocent_prompt", ev["guidance"])

    def test_case_listing_has_metadata(self):
        cases = self.cm.list_cases()
        for c in cases:
            self.assertIn("slug", c)
            self.assertIn("name", c)
            self.assertIn("summary", c)
            self.assertIn("difficulty", c)
            self.assertIn("evidence_count", c)
            self.assertGreater(c["evidence_count"], 0)


if __name__ == "__main__":
    unittest.main()
