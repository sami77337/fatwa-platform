"""Reuse PR204's fail-closed exact-SHA runner for author service and HTTP tests."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.dev import trusted_delivery_acceptance as runner

if __name__ == '__main__':
    runner.MODULES = [*runner.MODULES, 'tests.delivery_queue.test_author_handoff',
        'tests.delivery_queue.test_author_desk_http', 'tests.delivery_queue.test_approval_packet_context']
    runner.MINIMUM_CASES = 90
    raise SystemExit(runner.main())
