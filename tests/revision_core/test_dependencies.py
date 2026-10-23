"""Exercise cold service entry points without editorial or framework imports."""

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class ColdImportTests(unittest.TestCase):
    def check_entry_point(self, module, invocation):
        script = textwrap.dedent("""\
            import importlib
            import importlib.abc
            import socket
            import sys
            from unittest.mock import patch

            blocked = ('apps.editorial_demo', 'django', 'psycopg', 'psycopg2')

            class RejectDependency(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if any(fullname == name or fullname.startswith(name + '.')
                           for name in blocked):
                        raise AssertionError('Forbidden dependency: ' + fullname)
                    return None

            sys.meta_path.insert(0, RejectDependency())
            service = importlib.import_module(sys.argv[1])
            from apps.fatwa_drafts.domain import DraftRecord, Revision, State
            from apps.fatwa_drafts.intake import IntakeItem

            source = IntakeItem('SYN-CORE-COLD', 'Synthetic technical input.',
                                'https://example.invalid/synthetic')
            revision = Revision(1, 'synthetic_snapshot', 'Synthetic editor',
                                'Synthetic note', State.PREPARATION,
                                'Synthetic title', 'Synthetic text', (), '')
            record = DraftRecord(source, (revision,))
            with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
                    patch('builtins.open', side_effect=AssertionError('file access')):
                exec(sys.argv[2])
            assert not any(name == root or name.startswith(root + '.')
                           for name in sys.modules for root in blocked)
            print('Cold import and real invocation passed: ' + sys.argv[1])
        """)
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, module, invocation],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_cold_import_and_execution_do_not_require_editorial(self):
        self.check_entry_point(
            "apps.fatwa_drafts.revision_audit",
            "result = service.build_revision_audit(record, synthetic_fixtures_only=True); "
            "assert result.record is record; assert result.entries[0].revision is revision",
        )

    def test_history_cold_import_and_execution_do_not_require_editorial(self):
        self.check_entry_point(
            "apps.revision_core.revision_history",
            "result = service.build_history(record); assert result[0].revision is revision; "
            "assert service.select_revisions(result, '1', '1') == (revision, revision)",
        )

    def test_comparison_cold_import_and_execution_do_not_require_editorial(self):
        self.check_entry_point(
            "apps.revision_core.revision_comparison",
            "result = service.compare_revisions(revision, revision); "
            "assert not result.changed; assert result.fields[0].after[0].text == revision.title",
        )
