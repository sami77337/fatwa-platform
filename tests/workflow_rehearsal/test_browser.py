"""Real sandboxed Chrome exercises immutable, synthetic workflow navigation."""

import json
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from django.test import SimpleTestCase

from apps.editorial_workbench.services import build_cases
from tests.acceptance.fastbuild.test_browser import editorial_server


class WorkflowRehearsalBrowserTests(SimpleTestCase):
    def test_read_only_replay_keyboard_navigation_and_lossless_originals(self):
        # Expectations come from the pre-existing source adapter, independently
        # of the workflow replay and its presentation. DB access stays forbidden.
        originals = {
            case.key: {
                "question": case.question,
                "source": case.raw_source,
                "source_sha256": sha256(case.raw_source.encode("utf-8")).hexdigest(),
                "payload_sha256": case.payload_sha256,
            }
            for case in build_cases()
        }
        with tempfile.TemporaryDirectory(prefix="fatwa-workflow-originals-") as folder:
            expectation = Path(folder) / "originals.json"
            expectation.write_text(json.dumps(originals), encoding="utf-8")
            with editorial_server() as origin:
                result = subprocess.run(
                    [
                        "node",
                        str(Path(__file__).with_name("browser.mjs")),
                        origin,
                        str(expectation),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=150,
                )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
