"""Run lifecycle regressions in the Wave7 CI lane; never browser acceptance."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class BrowserStartupTests(unittest.TestCase):
    def test_protected_lifecycle_and_strict_diagnostics(self):
        root = Path(__file__).resolve().parents[3]
        environment = os.environ.copy()
        environment["FATWA_FASTBUILD_PYTHON"] = sys.executable
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tools/dev/wave4_node.py"),
                str(Path(__file__).with_name("startup.test.mjs")),
            ],
            cwd=root,
            env=environment,
            timeout=90,
            check=False,
        )
        self.assertEqual(result.returncode, 0, "Wave7 lifecycle regressions failed")
