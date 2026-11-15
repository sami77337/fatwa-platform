"""Reuse PR204's fail-closed exact-SHA runner for the author handoff suite."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.dev import trusted_delivery_acceptance as runner

if __name__ == '__main__':
    runner.MODULES = [*runner.MODULES, 'tests.delivery_queue.test_author_handoff']
    runner.MINIMUM_CASES = 74
    raise SystemExit(runner.main())
