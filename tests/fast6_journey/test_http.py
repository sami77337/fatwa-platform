"""Connected local reads of existing synthetic fixtures; no database or new identities."""

from hashlib import sha256
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase, override_settings

from apps.editorial_queue.services import build_queue_catalog
from apps.editorial_workbench.services import _asserted_catalog
from apps.reference_links import SnapshotCatalog


class Document(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.links, self.text = [], []
        # Match HTML's newline processing before decoding character references.
        self.feed(response.content.decode().replace("\r\n", "\n").replace("\r", "\n"))

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))

    def handle_data(self, data):
        self.text.append(data)


@override_settings(ALLOWED_HOSTS=["localhost", "remote.invalid"])
class ConnectedJourneyHTTPTests(SimpleTestCase):
    def setUp(self):
        # Explicit synthetic lookup substitution, never a PostgreSQL acceptance claim.
        catalog = SnapshotCatalog(_asserted_catalog())
        self.lookup = patch(
            "apps.reference_links.django_adapter.DjangoCatalog.lookup",
            side_effect=catalog.lookup,
        )
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.catalog = build_queue_catalog()

    def get(self, path, **kwargs):
        return self.client.get(path, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1", **kwargs)

    def follow(self, response, path):
        links = [link for link in Document(response).links if urlsplit(link).path == path]
        self.assertTrue(links, f"Missing existing navigation link: {path}")
        result = self.get(links[0])
        self.assertEqual(result.status_code, 200, links[0])
        return result

    def test_queue_history_packet_preserves_exact_revision_and_source_identity(self):
        index = self.get("/dev/editorial-queue")
        queue = self.follow(index, "/dev/editorial-queue/history")
        source = next(row for row in self.catalog.rows if row.case.key == "history")
        self.assertEqual(queue.context["selected"].case, source.case)
        selected_link = next(
            item["url"]
            for item in queue.context["history_rows"]
            if item["entry"].revision.number == 7
        )
        self.assertIn(selected_link, Document(queue).links)
        workbench = self.get(selected_link)
        packet_page = self.get(workbench.context["packet_url"])
        self.assertIn(workbench.context["packet_url"], Document(workbench).links)
        download = self.get(packet_page.context["packet_json_url"])
        packet = download.json()
        self.assertEqual(packet["identity"]["case_key"], source.case.key)
        self.assertEqual(packet["identity"]["external_id"], source.case.external_id)
        self.assertEqual(packet["selection"]["revision"], 7)
        self.assertEqual([item["number"] for item in packet["snapshots"]], [1, 2, 4, 7, 9, 11])
        self.assertEqual(packet["source"]["input_sha256"], source.case.payload_sha256)
        self.assertEqual(packet["source"]["text"], source.case.raw_source)
        self.assertEqual(download["X-Packet-SHA256"], sha256(download.content).hexdigest())
        self.assertEqual(download.content, self.get(packet_page.context["packet_json_url"]).content)
        for snapshot, revision in zip(packet["snapshots"], source.case.record.history, strict=True):
            self.assertEqual(snapshot["answer"], revision.answer)
        self.assertTrue(any("\r\n" in item["answer"] for item in packet["snapshots"]))
        self.assertEqual(packet["persisted_review"]["status"], "not_loaded")
        self.assertIsNone(packet["scholarly_decision"])

    def test_same_case_research_triage_rehearsal_and_packet_remain_connected(self):
        key = "intake-7"
        source = next(row.case for row in self.catalog.rows if row.case.key == key)
        queue = self.get(f"/dev/editorial-queue/{key}")
        workbench = self.follow(queue, f"/dev/editorial-workbench/{key}")
        before = self.get(workbench.context["packet_url"].replace("packet=html", "packet=json"))
        # Rehearsal supports the original nine cases only. Enter through its actual
        # index link; research does not currently provide a forward rehearsal link.
        rehearsal = self.follow(
            self.get("/dev/workflow-rehearsal"), f"/dev/workflow-rehearsal/{key}"
        )
        replay = rehearsal.context["rehearsal"]
        self.assertEqual(replay.case.key, key)
        self.assertEqual(replay.source_record, source.record)
        self.assertEqual(
            [step.accepted for step in replay.steps],
            [False, True, False, True, True, True, True, False],
        )
        triage = self.follow(rehearsal, f"/dev/reference-triage/{key}")
        research = self.follow(rehearsal, f"/dev/research-bridge/{key}")
        self.follow(research, f"/dev/reference-triage/{key}")
        self.follow(triage, f"/dev/editorial-workbench/{key}")
        for response in (triage, research):
            self.assertEqual(response.context["selected"].case.key, key)
            self.assertEqual(response.context["selected"].case.question, source.question)
            self.assertContains(response, source.payload_sha256)
            self.assertContains(response, 'lang="ar"')
            self.assertContains(response, 'dir="rtl"')
        verified = [
            entry["result"]
            for entry in research.context["references"]
            if entry["result"].status == "verified"
        ]
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].catalog_url, "/fiqh/nodes/2?edition=7001")
        self.assertIn(verified[0].catalog_url, Document(research).links)
        self.assertEqual(
            before.content,
            self.get(workbench.context["packet_url"].replace("packet=html", "packet=json")).content,
        )

    def test_csv_question_and_export_packet_keep_exact_bytes_and_permission_stays_denied(self):
        key = "batch-synthetic-csv-1"
        source = next(row.case for row in self.catalog.rows if row.case.key == key)
        self.assertIn("\r\n", source.question)
        # The packet's exact-text presentation preserves CR via character
        # references; the older ordinary workbench uses literal HTML newlines.
        for route in (
            f"/dev/editorial-workbench/{key}?packet=html",
            f"/dev/reference-triage/{key}",
            f"/dev/research-bridge/{key}",
        ):
            page = self.get(route)
            self.assertEqual(page.status_code, 200)
            self.assertIn(source.question, "".join(Document(page).text))
        exports = self.get("/dev/editorial-export")
        report = self.follow(exports, "/dev/editorial-export/report.json").json()
        item = next(
            item for item in report["cases"] if item["packet"]["identity"]["case_key"] == key
        )
        self.assertIn(item["navigation"]["packet_path"], Document(exports).links)
        packet_page = self.get(item["navigation"]["packet_path"])
        self.assertEqual(packet_page.context["packet"], item["packet"])
        self.assertEqual(item["packet"]["intake"]["question"], source.question)
        permission = self.get(
            "/dev/permission-lab",
            data={"actor": "MUFTI", "action": "start_review", "resource": "workflow::UNREVIEWED"},
        )
        self.assertEqual(permission.status_code, 200)
        self.assertEqual(permission.context["decision"].effect, "DENY")
        self.assertIs(permission.context["decision"].allowed, False)
        self.follow(permission, "/dev/editorial-dashboard")
        self.assertEqual(self.get(f"/dev/workflow-rehearsal/{key}").status_code, 404)

    def test_connected_route_selectors_and_write_methods_fail_closed(self):
        invalid = {
            "/dev/editorial-queue/history?status=approved": 400,
            "/dev/editorial-workbench/history?revision=07&packet=json": 400,
            "/dev/editorial-workbench/history?revision=3&packet=json": 404,
            "/dev/reference-triage/history?edition_id=7001": 400,
            "/dev/research-bridge/intake-7?source_row_id=2": 400,
            "/dev/workflow-rehearsal/intake-7?step=01": 400,
            "/dev/editorial-export/report.json?file=private": 400,
            "/dev/permission-lab?actor=MUFTI": 400,
        }
        for route, status in invalid.items():
            with self.subTest(route=route):
                self.assertEqual(self.get(route).status_code, status)
        routes = (
            "/dev/editorial-queue/history",
            "/dev/editorial-workbench/history?packet=json",
            "/dev/reference-triage/history",
            "/dev/research-bridge/history",
            "/dev/workflow-rehearsal/intake-7",
            "/dev/editorial-export/report.json",
            "/dev/permission-lab",
        )
        for route in routes:
            with self.subTest(route=route):
                head = self.client.head(route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1")
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                for method in ("post", "put", "patch", "delete"):
                    response = getattr(self.client, method)(
                        route, HTTP_HOST="localhost", REMOTE_ADDR="127.0.0.1"
                    )
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response["Allow"], "GET, HEAD")
                self.assertEqual(
                    self.client.get(
                        route, HTTP_HOST="remote.invalid", REMOTE_ADDR="127.0.0.1"
                    ).status_code,
                    404,
                )
