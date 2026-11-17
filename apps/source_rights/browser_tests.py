"""Actual staff forms: independent source rights, knowledge review and citation correction."""

import json
import os
from pathlib import Path

from django.test import LiveServerTestCase, override_settings

from apps.casework.models import AnswerRevision, Case
from apps.knowledge_links.models import KnowledgeRevision

from .tests import ENABLED, RightsFixture


@override_settings(**{**ENABLED, "FATWA_CASEWORK_WEB_ENABLED": True})
class SourceRightsBrowserTests(RightsFixture, LiveServerTestCase):
    host = "127.0.0.1"

    def test_human_rights_review_relationship_and_canonical_correction_rtl(self):
        from playwright.sync_api import sync_playwright

        old_authenticate = self.directory.authenticate
        self.directory.authenticate = lambda credential: (
            self.directory.resolve("publisher")
            if credential == "synthetic-publisher-credential-32-characters"
            else old_authenticate(credential)
        )
        errors, external = [], []
        with (
            override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path=os.environ.get("FATWA_FASTBUILD_BROWSER", "/usr/bin/chromium"),
                headless=True,
                chromium_sandbox=os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
            )
            try:

                def open_desk(page):
                    with page.expect_navigation():
                        page.evaluate(
                            """fields => {
                            const f=document.createElement('form'); f.method='POST';f.action='/casework/staff/';
                            fields.csrfmiddlewaretoken=document.querySelector('[name=csrfmiddlewaretoken]').value;
                            for(const [name,value] of Object.entries(fields)){const i=document.createElement('input');i.name=name;i.value=value;f.appendChild(i);}
                            document.body.appendChild(f);f.submit();
                        }""",
                            {
                                "action": "rights_desk",
                                "case_ref": self.receipt["public_ref"],
                                "query": "",
                                "edition_id": "",
                            },
                        )

                def login(subject, width):
                    context = browser.new_context(viewport={"width": width, "height": 900})
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "request",
                        lambda request: (
                            external.append(request.url)
                            if not request.url.startswith(self.live_server_url + "/")
                            else None
                        ),
                    )
                    page.goto(self.live_server_url + "/casework/staff/login/")
                    page.locator('[name="credential"]').fill(
                        f"synthetic-{subject}-credential-32-characters"
                    )
                    page.get_by_role("button", name="دخول المكتب", exact=True).click()
                    open_desk(page)
                    return page

                editor = login("editor", 320)
                self.assertIn("UNKNOWN", editor.content())
                proposal = editor.locator(
                    'form:has(input[name="action"][value="rights_propose"])'
                ).first
                for usage in ("READ", "CITE", "RELATE", "PREVIEW_METADATA"):
                    proposal.locator(f'[name="uses"][value="{usage}"]').check()
                proposal.locator('[name="basis"]').fill(
                    "Synthetic human reviewed permission record"
                )
                proposal.locator('[name="note"]').fill("PRIVATE registration rationale")
                proposal.get_by_role("button").click()
                self.assertIn("PENDING", editor.content())
                publisher = login("publisher", 1280)
                review = publisher.locator(
                    'form:has(input[name="action"][value="rights_review"])'
                ).first
                review.locator('[name="note"]').fill("Human independent rights review")
                review.locator('[name="confirm"]').check()
                review.get_by_role("button").click()
                self.assertIn("ALLOWED", publisher.content())
                editor.locator("#rights-edition").select_option(str(self.catalog_id))
                editor.locator("#rights-query").fill("فرع")
                editor.get_by_role("button", name="بحث المصادر الحالية", exact=True).click()
                relation = editor.locator(
                    f'form:has(input[value="rights_relation_propose"]):has(input[name="target_id"][value="{self.heading.pk}"])'
                )
                relation.locator('[name="note"]').fill(
                    "Human relationship suggestion using existing citation"
                )
                relation.get_by_role("button").click()
                open_desk(publisher)
                relation_review = publisher.locator(
                    'form:has(input[value="rights_relation_action"])'
                ).first
                relation_review.locator('[name="confirm"]').check()
                relation_review.get_by_role("button").click()
                self.assertIn("APPROVED", publisher.content())
                editor.locator("#rights-edition").select_option(str(self.catalog_id))
                editor.locator("#rights-query").fill("فرع")
                editor.get_by_role("button", name="بحث المصادر الحالية", exact=True).click()
                correction = editor.locator(
                    f'form:has(input[value="rights_citation_correct"]):has(input[name="target_id"][value="{self.heading.pk}"])'
                )
                correction.locator('[name="note"]').fill(
                    "Human correction preserves source and appends editorial note"
                )
                correction.get_by_role("button").click()
                self.assertIn("مراجعة 5", editor.content())
                for page in (editor, publisher):
                    self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                    self.assertFalse(
                        page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    )
                    page.keyboard.press("Tab")
                    self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY")
                output = Path(".local/qa/source-rights")
                output.mkdir(parents=True, exist_ok=True)
                (output / "browser.json").write_text(
                    json.dumps(
                        {
                            "browser": browser.version,
                            "sandbox": os.environ.get("FATWA_TEST_BROWSER_NO_SANDBOX") != "1",
                            "widths": [320, 1280],
                            "rights": "independently reviewed",
                            "relation": "canonically approved",
                            "citation": "canonical new answer revision",
                            "errors": errors,
                            "external_requests": external,
                        },
                        indent=2,
                    )
                )
            finally:
                browser.close()
        self.assertEqual(errors, [])
        self.assertEqual(external, [])
        self.assertEqual(AnswerRevision.objects.count(), 2)
        self.assertEqual(Case.objects.get(pk=self.receipt["case_id"]).stage, "UNDER_REVIEW")
        self.assertEqual(KnowledgeRevision.objects.count(), 1)
