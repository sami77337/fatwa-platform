"""Prove the pure entry points remain usable without Django, databases or I/O."""

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class PureDependencyTests(unittest.TestCase):
    def test_cold_import_and_real_invocations_with_framework_and_io_denied(self):
        script = textwrap.dedent(
            """\
            import importlib.abc
            import socket
            import sys
            from unittest.mock import patch

            blocked = ('django', 'psycopg', 'psycopg2', 'apps.editorial_demo')

            class RejectDependency(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if any(fullname == name or fullname.startswith(name + '.')
                           for name in blocked):
                        raise AssertionError('Forbidden dependency: ' + fullname)
                    return None

            sys.meta_path.insert(0, RejectDependency())
            from apps.arabic_text_quality.service import (
                inspect_text, compare_texts, inspect_revision,
            )
            from apps.fatwa_drafts.domain import Revision, State

            revision = Revision(1, 'synthetic', 'synthetic', 'synthetic',
                                State.RECEIVED, 'synthetic', 'a  b', (), '')
            with patch.object(socket, 'socket', side_effect=AssertionError('network')), \\
                    patch('builtins.open', side_effect=AssertionError('file access')):
                assert inspect_text('synthetic', synthetic_only=True).sources
                assert compare_texts('a b', 'a  b', synthetic_only=True).diagnostics
                assert inspect_revision(revision, synthetic_only=True).sources
            assert not any(name == root or name.startswith(root + '.')
                           for name in sys.modules for root in blocked)
            """
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
