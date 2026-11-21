"""Protected native two-human taxonomy versions, exact mappings and rollback."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.db import close_old_connections, connections
from django.test import LiveServerTestCase, override_settings

from .models import CaseClassification, Concept, HumanReview, MigrationExecution, TreeVersion
from .recovery_support import original_digest
from .test_support import FEATURES, TaxonomyFixture, initial_nodes

OUT = Path(".local/qa/functional-continuation/taxonomy-browser")


@override_settings(**{**FEATURES, "FATWA_MUFTI_WORKSPACE_ENABLED": True})
class DevelopmentTaxonomyBrowserTests(TaxonomyFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def sync(self, operation):
        def work():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(work).result(timeout=30)

    def submit(self, page, button, expected=200):
        # This long two-human journey shares the real loopback request budget.
        # Pace native actions across its fixed minute windows; never clear the
        # durable throttle or raise the application limit to make the test pass.
        window = int(time.time()) // 60
        if getattr(self, "_post_window", None) != window:
            self._post_window, self._post_count = window, 0
        if self._post_count >= 45:
            remaining = (window + 1) * 60 - time.time() + 0.2
            page.wait_for_timeout(max(0, int(remaining * 1000)))
            self._post_window, self._post_count = int(time.time()) // 60, 0
        self._post_count += 1
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            button.focus()
            button.press("Enter")
        self.assertEqual(response.value.status, expected, page.locator("body").inner_text()[:1600])
        self.assertIn("no-store", response.value.headers.get("cache-control", ""))

    def login(self, page, subject):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/login/").status, 200)
        name = {"editor": "editor", "other": "reviewer"}[subject]
        page.locator("#credential").fill(f"synthetic-{name}-credential-32-characters")
        with page.expect_navigation(wait_until="domcontentloaded") as response:
            page.get_by_role("button", name="دخول المكتب", exact=True).click()
        self.assertEqual(response.value.status, 200)

    def open_case(self, page, receipt, version_id=None):
        self.assertEqual(page.goto(self.live_server_url + "/casework/staff/").status, 200)
        form = page.locator(
            f'form:visible:has([name="case_ref"][value="{receipt["public_ref"]}"]):has([name="action"][value="open"])'
        ).first
        self.submit(page, form.locator("button").first)
        form = page.locator('form:visible:has([name="action"][value="dt_open"])').first
        self.assertEqual(form.count(), 1)
        self.submit(page, form.locator("button").first)
        if version_id:
            form = page.locator("#dt-open")
            form.locator('[name="version_id"]').select_option(version_id)
            self.submit(page, form.locator("button"))

    def screenshots(self, page, name):
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            page.screenshot(path=str(OUT / f"{name}-{width}.png"), full_page=True)

    def confirm(self, page, form, button=None):
        form.locator('[name="reason"]').fill("إجراء بشري موثق على بيانات اصطناعية صرفة")
        form.locator('[name="confirmed"]').check()
        self.submit(page, button if button is not None else form.locator("button"))

    def save_tree(self, page):
        form = page.locator("#dt-tree")
        self.confirm(page, form, form.locator('button[value="save"]'))
        identifier = page.locator('#dt-tree [name="version_id"]').input_value()
        return self.sync(lambda: TreeVersion.objects.get(pk=identifier))

    def review_tree(self, page, identifier):
        self.open_case(page, self.receipt, str(identifier))
        form = page.locator("#dt-version-review")
        self.confirm(page, form, form.locator('button[value="APPROVE"]'))

    def bind_native(self, page, receipt, version, primary, additional):
        self.open_case(page, receipt, str(version.pk))
        form = page.locator("#dt-bind")
        form.locator('[name="primary"]').select_option(primary)
        for identifier in additional:
            form.locator(f'[name="additional"][value="{identifier}"]').check()
        self.confirm(page, form)

    def plan_native(self, page, source, target, mappings, resolutions):
        self.open_case(page, self.receipt)
        form = page.locator("#dt-compare")
        form.locator('[name="source_version_id"]').select_option(str(source.pk))
        form.locator('[name="target_version_id"]').select_option(str(target.pk))
        self.submit(page, form.locator("button"))
        form = page.locator("#dt-mapping")
        for identifier, kind, targets in mappings:
            row = form.locator(f'[data-mapping-source="{identifier}"]')
            row.locator(f'[name="map_kind_{identifier}"]').select_option(kind)
            choices = row.locator(f'[name="map_target_{identifier}"]')
            for index in range(choices.count()):
                choice = choices.nth(index)
                choice.set_checked(choice.input_value() in targets)
            row.locator(f'[name="map_reason_{identifier}"]').fill(
                "قارنت تعريف المعنى والنسخ، وحددت هذه العلاقة دون تخمين"
            )
        self.submit(page, form.locator("button"))
        impact = page.locator("#dt-impact")
        self.assertEqual(impact.locator("[data-impact-case]").count(), len(resolutions))
        before = self.sync(lambda: CaseClassification.objects.count())
        form = page.locator("#dt-plan")
        for receipt, primary, additional in resolutions:
            identifier = receipt["case_id"]
            row = form.locator(f'[data-impact-case="{identifier}"]')
            self.assertIn(receipt["public_ref"], row.inner_text())
            if primary is None:
                self.assertEqual(
                    row.locator(f'[name="resolution_hold_{identifier}"]').input_value(), "yes"
                )
                self.assertIn("بلا مقابل", row.inner_text())
                self.assertEqual(row.locator("select").count(), 0)
            else:
                row.locator(f'[name="resolution_primary_{identifier}"]').select_option(primary)
                for additional_id in additional:
                    row.locator(
                        f'[name="resolution_additional_{identifier}"][value="{additional_id}"]'
                    ).check()
            row.locator(f'[name="resolution_reason_{identifier}"]').fill(
                "إبقاء الرابط القديم لغياب المقابل"
                if primary is None
                else "اختيار بشري دقيق لهذه القضية"
            )
        self.screenshots(page, f"impact-v{target.number}")
        self.confirm(page, form)
        self.assertEqual(self.sync(lambda: CaseClassification.objects.count()), before)
        return page.locator("[data-taxonomy-plan]").last.get_attribute("data-taxonomy-plan")

    def review_plan(self, page, identifier):
        self.open_case(page, self.receipt)
        form = page.locator(f'[data-taxonomy-plan="{identifier}"] .dt-plan-review')
        self.confirm(page, form, form.locator('button[value="APPROVE"]'))

    def execute(self, page, identifier, kind="apply"):
        self.open_case(page, self.receipt)
        form = page.locator(f'[data-taxonomy-plan="{identifier}"] .dt-plan-{kind}')
        self.confirm(page, form)

    def binding(self, receipt):
        return self.sync(
            lambda: (
                CaseClassification.objects.filter(case_id=receipt["case_id"])
                .order_by("-sequence")
                .values("version_id", "primary_id", "additional", "sequence")
                .first()
            )
        )

    def test_native_multilevel_ids_primary_additional_reviewed_migrations_and_rollback(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("FATWA_BROWSER_SANDBOX") != "1":
            self.fail("Protected browser proof requires FATWA_BROWSER_SANDBOX=1")
        second, _ = self.new_case()
        case_ids = [self.receipt["case_id"], second["case_id"]]
        originals = original_digest(case_ids)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "result.json").unlink(missing_ok=True)
        errors, external, contexts = [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                chromium_sandbox=True,
                args=["--disable-dev-shm-usage"],
            )

            def page():
                context = browser.new_context(viewport={"width": 320, "height": 900})
                contexts.append(context)

                def route(request):
                    target = urlsplit(request.request.url)
                    if (
                        target.scheme != "http"
                        or target.netloc != urlsplit(self.live_server_url).netloc
                    ):
                        external.append(request.request.url)
                        request.abort()
                    else:
                        request.continue_()

                context.route("**/*", route)
                context.tracing.start(screenshots=True, snapshots=True)
                result = context.new_page()
                result.on("pageerror", lambda error: errors.append(str(error)))
                return result

            try:
                author, reviewer = page(), page()
                self.login(author, "editor")
                self.login(reviewer, "other")
                self.open_case(author, self.receipt)
                form = author.locator("#dt-tree")
                form.locator('[name="title"]').fill("شجرة فقهية اصطناعية مستقلة")
                form.locator('[name="provenance"]').fill(
                    "مفاهيم اصطناعية للتطوير؛ ليست شجرة شرعية نهائية أو فهرس كتاب 622"
                )
                for values in initial_nodes():
                    row = form.locator(f'[data-node-key="{values["key"]}"]')
                    row.locator('[name="node_name"]').fill(values["name"])
                    row.locator('[name="node_parent"]').select_option(values["parent"])
                    row.locator('[name="node_definition"]').fill(values["definition"])
                source = self.save_tree(author)
                keys = [row["id"] for row in source.nodes]
                self.assertEqual(author.locator("#dt-outline details").count(), 4)
                self.assertEqual(
                    author.locator("#dt-outline > li > details > ol > li > details > ol").count(), 1
                )
                root = author.locator("#dt-outline > li > details").first
                root.locator(":scope > summary").press("Enter")
                self.assertIsNone(root.get_attribute("open"))
                root.locator(":scope > summary").press("Enter")
                self.assertIsNotNone(root.get_attribute("open"))
                self.assertEqual(author.locator("#dt-version-review").count(), 0)
                self.screenshots(author, "multilevel-draft")
                self.review_tree(reviewer, source.pk)
                self.bind_native(author, self.receipt, source, keys[1], [keys[3]])
                self.bind_native(author, second, source, keys[2], [])
                self.open_case(author, self.receipt, str(source.pk))
                row = author.locator(f'#dt-tree [data-node-key="{keys[1]}"]')
                row.locator('[name="node_name"]').fill("باب ألف بعد تصحيح الاسم")
                author.locator(
                    f'#dt-tree [data-node-key="{keys[2]}"] [name="node_parent"]'
                ).select_option(keys[3])
                target = self.save_tree(author)
                self.assertEqual([row["id"] for row in target.nodes], keys)
                self.assertEqual(target.nodes[2]["parent"], keys[3])
                self.assertEqual(self.binding(self.receipt)["version_id"], source.pk)
                self.review_tree(reviewer, target.pk)
                mappings = [
                    (key, "RENAMED" if index == 1 else "MOVED" if index == 2 else "SAME", [key])
                    for index, key in enumerate(keys)
                ]
                plan = self.plan_native(
                    author,
                    source,
                    target,
                    mappings,
                    [(self.receipt, keys[1], [keys[3]]), (second, keys[2], [])],
                )
                self.assertEqual(
                    author.locator(f'[data-taxonomy-plan="{plan}"] .dt-plan-apply').count(), 0
                )
                self.review_plan(reviewer, plan)
                self.execute(author, plan)
                self.assertEqual(self.binding(self.receipt)["version_id"], target.pk)
                self.assertEqual(self.binding(second)["version_id"], target.pk)
                self.execute(author, plan, "rollback")
                self.assertEqual(self.binding(self.receipt)["version_id"], source.pk)
                self.assertEqual(self.binding(second)["version_id"], source.pk)
                self.assertEqual(self.binding(self.receipt)["sequence"], 3)
                self.screenshots(author, "exact-rollback")

                # A split creates new meanings/identities; the old missing leaf
                # has no inferred equivalent and its second case remains held.
                self.open_case(author, self.receipt, str(target.pk))
                for key in keys[1:3]:
                    author.locator(f'#dt-tree [data-node-key="{key}"] [name="node_name"]').fill("")
                for index in range(2):
                    row = author.locator(f'#dt-tree [data-node-key="new:{index}"]')
                    row.locator('[name="node_name"]').fill(f"جزء اصطناعي جديد {index + 1}")
                    row.locator('[name="node_parent"]').select_option(keys[0])
                    row.locator('[name="node_definition"]').fill(
                        f"تعريف اصطناعي جديد للجزء {index + 1}"
                    )
                split = self.save_tree(author)
                new_keys = [row["id"] for row in split.nodes[2:]]
                self.assertTrue(set(new_keys).isdisjoint(keys))
                self.review_tree(reviewer, split.pk)
                split_plan = self.plan_native(
                    author,
                    source,
                    split,
                    [
                        (keys[0], "SAME", [keys[0]]),
                        (keys[1], "SPLIT", new_keys),
                        (keys[2], "NO_EQUIVALENT", []),
                        (keys[3], "MOVED", [keys[3]]),
                    ],
                    [(self.receipt, new_keys[0], [new_keys[1], keys[3]]), (second, None, [])],
                )
                self.review_plan(reviewer, split_plan)
                self.execute(author, split_plan)
                self.assertEqual(str(self.binding(self.receipt)["primary_id"]), new_keys[0])
                self.assertEqual(
                    set(self.binding(self.receipt)["additional"]), {new_keys[1], keys[3]}
                )
                self.assertEqual(self.binding(second)["version_id"], source.pk)
                self.assertEqual(self.binding(second)["sequence"], 3)

                # A subsequent explicit merge also gets a fresh identity; no
                # renamed ID is reused for a new combined meaning.
                self.open_case(author, self.receipt, str(split.pk))
                for key in new_keys:
                    author.locator(f'#dt-tree [data-node-key="{key}"] [name="node_name"]').fill("")
                row = author.locator('#dt-tree [data-node-key="new:0"]')
                row.locator('[name="node_name"]').fill("مفهوم مركب اصطناعي جديد")
                row.locator('[name="node_parent"]').select_option(keys[0])
                row.locator('[name="node_definition"]').fill(
                    "معنى اصطناعي مركب مستقل عن الهويات السابقة"
                )
                merged = self.save_tree(author)
                merged_key = merged.nodes[2]["id"]
                self.assertNotIn(merged_key, [*keys, *new_keys])
                self.review_tree(reviewer, merged.pk)
                merged_plan = self.plan_native(
                    author,
                    split,
                    merged,
                    [
                        (keys[0], "SAME", [keys[0]]),
                        (keys[3], "SAME", [keys[3]]),
                        *[(key, "MERGED", [merged_key]) for key in new_keys],
                    ],
                    [(self.receipt, merged_key, [keys[3]])],
                )
                self.review_plan(reviewer, merged_plan)
                self.execute(author, merged_plan)
                self.assertEqual(str(self.binding(self.receipt)["primary_id"]), merged_key)
                self.assertEqual(self.binding(second)["version_id"], source.pk)
                self.assertEqual(self.sync(lambda: Concept.objects.count()), 7)
                self.assertEqual(self.sync(lambda: TreeVersion.objects.count()), 4)
                self.assertEqual(self.sync(lambda: HumanReview.objects.count()), 7)
                self.assertEqual(self.sync(lambda: MigrationExecution.objects.count()), 4)
                self.assertEqual(self.sync(lambda: CaseClassification.objects.count()), 8)
                self.assertEqual(self.sync(lambda: original_digest(case_ids)), originals)
                self.screenshots(author, "split-merge-history")
                self.sync(lambda: self.authority.denied.add("READ"))
                self.submit(author, author.locator("#dt-open button"), expected=409)
                self.assertNotIn("مفهوم مركب اصطناعي جديد", author.locator("body").inner_text())
                self.assertEqual(errors, [])
                self.assertEqual(external, [])
                for index, context in enumerate(contexts):
                    context.tracing.stop(path=str(OUT / f"actor-{index}-trace.zip"))
                (OUT / "result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "sandbox": True,
                            "widths": [320, 1280],
                            "independent_humans": 2,
                            "versions": 4,
                            "stable_concepts": 7,
                            "reviewed_plans": 3,
                            "actual_executions": 4,
                            "classification_rows": 8,
                            "checks": [
                                "native multilevel tree and keyboard expansion",
                                "primary and additional classifications on approved canonical answers",
                                "stable IDs across rename and move",
                                "independent version and mapping reviews",
                                "exact two-case dry run actual migration and rollback",
                                "explicit split and merge with new identities",
                                "missing equivalent preserves original binding",
                                "unchanged original cases answers decisions and source evidence",
                                "current reader revocation",
                            ],
                            "page_errors": errors,
                            "external_requests": external,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            finally:
                for index, context in enumerate(contexts):
                    if not (OUT / f"actor-{index}-trace.zip").exists():
                        try:
                            context.tracing.stop(path=str(OUT / f"actor-{index}-trace.zip"))
                        except Exception:
                            pass
                    context.close()
                browser.close()
