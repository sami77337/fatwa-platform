"""Independent-review regressions: bounded composition, map scans and row links."""
from copy import deepcopy
from dataclasses import asdict
from html.parser import HTMLParser
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from apps.editorial_demo import integration
from apps.fatwa_drafts.intake import ReferenceLink
from apps.prepared_pipeline import C1Pointer, ExplicitMapping
from apps.reference_links.bridge import BridgeConfig, HeadingMap
from apps.reference_links.resolution import Heading, SnapshotCatalog


def encode(items):
    return json.dumps({"schema": integration.SCHEMA, "items": items}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def mapped_batch(mapping_count=20_000, row_count=20, reference_count=100):
    """Reputable-registry-free deterministic benchmark; invented source identity only."""
    _, seed, _ = integration._synthetic_dependencies()
    identity = seed.edition.identity
    headings = tuple(HeadingMap("s", str(i), "c" + str(i), i + 1) for i in range(mapping_count))
    bridge = BridgeConfig(seed.edition, headings)
    mapping = {
        C1Pointer(h.c1_source_id, h.c1_heading_id): ExplicitMapping(
            ReferenceLink(**asdict(identity), source_id=h.c2_source_id),
            bridge.edition.edition_id, h.source_row_id, "synthetic-review-fixture",
        ) for h in headings
    }
    selected = headings[-row_count * reference_count:]
    catalog = SnapshotCatalog(tuple(
        Heading(41, h.source_row_id, "مرجع اصطناعي", "عنوان اصطناعي", "الأول", 12,
                ("عنوان اصطناعي",), identity.source_namespace, identity.source_book_id,
                identity.source_input_sha256) for h in selected
    ))
    items = [{"external_id": "S" + str(row), "question": "سؤال اصطناعي",
              "prepared_clip_url": "https://example.invalid/clip.mp4",
              "reference_links": [{"source_id": h.c1_source_id, "heading_id": h.c1_heading_id}
                                  for h in selected[row * reference_count:(row + 1) * reference_count]]}
             for row in range(row_count)]
    return encode(items), mapping, bridge, catalog


class CompositionReviewTests(SimpleTestCase):
    def compose(self, raw, **overrides):
        mapping, bridge, catalog = integration._synthetic_dependencies()
        return integration.compose_synthetic_batch(raw, synthetic_fixtures_only=True,
            **({"reference_map": mapping, "bridge_config": bridge, "catalog": catalog} | overrides))

    def test_reference_evidence_does_not_rescan_full_mapping_per_pointer(self):
        raw, mapping, bridge, catalog = mapped_batch(row_count=2, reference_count=10)
        descriptor = HeadingMap.c1_source_id
        reads = 0

        def counted(instance):
            nonlocal reads
            reads += 1
            return descriptor.__get__(instance, HeadingMap)

        with patch.object(HeadingMap, "c1_source_id", property(counted)):
            rows = integration.compose_synthetic_batch(
                raw, synthetic_fixtures_only=True,
                reference_map=mapping, bridge_config=bridge, catalog=catalog,
            )
        self.assertEqual(sum(len(row.references) for row in rows), 20)
        self.assertTrue(all(ref.status == "verified" for row in rows for ref in row.references))
        # One index in D3 and one local evidence index in E2; no timing threshold.
        self.assertLessEqual(reads, 2 * len(bridge.headings))

    def test_near_limit_raw_does_not_expand_past_d3_byte_bound(self):
        items = [{"external_id": "S" + str(i), "question": "سؤال اصطناعي" + "x" * 1000,
                  "prepared_clip_url": "", "reference_links": []} for i in range(800)]
        padding, remainder = divmod(999_999 - len(encode(items)), len(items))
        self.assertGreaterEqual(padding, 0)
        for item in items:
            item["question"] += "x" * padding
        items[-1]["question"] += "x" * remainder
        raw = encode(items)
        self.assertEqual(len(raw), 999_999)
        real_resolve = integration.resolve_prepared_pointers
        observed_sizes = []

        def bounded(payload, config, catalog):
            observed_sizes.append(len(payload))
            if len(payload) > 1_000_000:
                raise ValueError("D3 input exceeds bound")
            return real_resolve(payload, config, catalog)

        with patch.object(integration, "resolve_prepared_pointers", side_effect=bounded):
            rows = self.compose(raw)
        self.assertEqual(len(rows), 800)
        self.assertEqual([row.question for row in rows], [item["question"] for item in items])
        self.assertTrue(observed_sizes)
        self.assertLessEqual(max(observed_sizes), len(raw))

    def test_d3_incompatible_id_does_not_drop_valid_siblings_or_change_originals(self):
        first = deepcopy(integration._SYNTHETIC_ROWS[0])
        for ident in ("SYN\tUNSEEN", "SYN\nUNSEEN", "SYN\x7fUNSEEN"):
            with self.subTest(ident=repr(ident)):
                other = {**first, "external_id": ident, "question": "  سؤالٌ اصطناعي\tمستقل  "}
                raw = encode([first, other])
                mapping, _, catalog = integration._synthetic_dependencies()
                prepared = integration.prepare_batch(raw, synthetic_fixtures_only=True,
                                                      reference_map=mapping, catalog=catalog)
                received = prepared.report["items"][1]
                rows = self.compose(raw)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0].status, "ready-for-editor")
                self.assertEqual(rows[1].external_id, ident)
                self.assertEqual(rows[1].question, other["question"])
                # Wave6 E1 will block control IDs; base D1 permits some. E2 must
                # honor D1's rejection and otherwise isolate D3's stricter ID rule.
                expected = "blocked-invalid" if "blocked-invalid" in received["statuses"] else "needs-editor-review"
                self.assertEqual(rows[1].status, expected)
                self.assertEqual(rows[1].draft_created, received["draft"] is not None)
                self.assertTrue(all(ref.citation is None for ref in rows[1].references))
                self.assertIn("invalid_input", rows[1].issue_codes)


class HeadingLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.in_heading = True
        if tag == "a" and self.in_heading:
            self.links.append(dict(attrs).get("href"))

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_heading = False


class RowSelectionReviewTests(SimpleTestCase):
    url = "/dev/editorial-preview/pipeline"

    def get(self, suffix=""):
        return self.client.get(self.url + suffix, HTTP_HOST="localhost")

    def links(self, response):
        parser = HeadingLinks()
        parser.feed(response.content.decode())
        return parser.links

    def test_all_retained_rows_have_distinct_safe_links_including_slash_and_missing_ids(self):
        seed = deepcopy(integration._SYNTHETIC_ROWS[0])
        items = ({**seed, "external_id": "VALID-SIBLING"},
                 {**seed, "external_id": "BLOCKED/UNSEEN", "question": None},
                 {**seed, "external_id": "DUP", "question": "سؤال اصطناعي أول"},
                 {**seed, "external_id": "DUP", "question": "سؤال اصطناعي ثان"}, 7)
        query = "?batch=mixed&status=blocked-invalid&issue=invalid_input&page_size=1&page=1"
        seen = []
        with patch.object(integration, "_MIXED_ROWS", items):
            for page in range(1, 5):
                response = self.get(query.replace("page=1", "page=" + str(page)))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["rows"]), 1)
                links = self.links(response)
                self.assertEqual(len(links), 1)
                seen.extend(links)
                parsed = urlsplit(links[0])
                self.assertEqual(parsed.path, self.url)
                self.assertEqual(parse_qs(parsed.query)["row"], [str(page + 1)])
                detail = self.client.get(links[0], HTTP_HOST="localhost")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.context["row"], response.context["rows"][0])
                self.assertNotIn("row", parse_qs(detail.context["filter_query"]))
                returned = self.get("?" + detail.context["filter_query"])
                self.assertEqual(returned.context["rows"], response.context["rows"])
            self.assertEqual(self.get("/DUP?batch=mixed").status_code, 404)
        self.assertEqual(len(set(seen)), 4)

    def test_row_selection_uses_selected_batch_and_keeps_legacy_unique_id_urls(self):
        default = self.get("?row=1")
        alternate = self.get("?row=1&batch=mixed")
        self.assertEqual(default.status_code, 200)
        self.assertEqual(alternate.status_code, 200)
        self.assertIsNotNone(default.context["row"])
        self.assertIsNotNone(alternate.context["row"])
        self.assertNotEqual(default.context["row"].question, alternate.context["row"].question)
        self.assertEqual(self.get("/SYN-P01").context["row"], default.context["row"])

    def test_invalid_duplicate_conflicting_or_out_of_range_row_selection(self):
        with patch("apps.editorial_demo.views.build_preview_rows", side_effect=AssertionError("forbidden")):
            for suffix in ("?row=", "?row=0", "?row=-1", "?row=01", "?row=1001", "?row=١",
                           "?row=1&row=2", "/SYN-P01?row=1", "?row=../private"):
                self.assertEqual(self.get(suffix).status_code, 400)
        self.assertEqual(self.get("?row=1000").status_code, 404)
