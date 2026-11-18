"""Static evidence planning must never become execution credit."""

import copy
import unittest

import build


class DraftAnchorsTests(unittest.TestCase):
    def test_exact_static_symbols_and_original_point_spec_links(self):
        rendered = build.draft_anchors_document()
        self.assertIn("STATIC_CODE_REVIEW_ONLY", rendered)
        self.assertIn("Candidate points retain original SPEC links", rendered)
        self.assertIn("No formal taxonomy registry", rendered)
        self.assertIn("AUTHOR_PROPOSED_REVIEW_PENDING", rendered)

    def test_static_review_cannot_credit_points_or_claim_execution(self):
        draft = build.read("draft_anchors.json")
        for key, value in (("execution_state", "PASS"), ("credited_owner_points", [70])):
            changed = copy.deepcopy(draft)
            changed[key] = value
            with self.assertRaises(AssertionError):
                build.draft_anchors_document(changed)

    def test_missing_or_duplicated_test_reference_is_rejected(self):
        draft = build.read("draft_anchors.json")
        draft["groups"][0]["positive_tests"] = ["apps/browser_audio/context.py#invented_test"]
        with self.assertRaises(AssertionError):
            build.draft_anchors_document(draft)
        draft = build.read("draft_anchors.json")
        tests = draft["groups"][0]["positive_tests"]
        tests.append(tests[0])
        with self.assertRaises(AssertionError):
            build.draft_anchors_document(draft)
