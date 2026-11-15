"""Exact-SHA regression runner reusing the owned synthetic DB contract."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.dev import trusted_delivery_acceptance as runner

if __name__ == '__main__':
    runner.MODULES = [*runner.MODULES, 'tests.delivery_queue.test_author_handoff',
        'tests.delivery_queue.test_author_desk_http', 'tests.delivery_queue.test_approval_packet_context',
        'tests.mufti_review.test_cycle', 'tests.mufti_review.test_http']
    runner.MINIMUM_CASES = 119
    raise SystemExit(runner.main())
