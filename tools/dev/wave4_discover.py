"""Explicit per-directory discovery, including namespace test directories."""
from pathlib import Path
import subprocess
import sys


def main():
    folder = Path(sys.argv[1]).resolve()
    if not folder.is_dir():
        return 2
    directories = sorted({p.parent for p in folder.rglob('test*.py')})
    if not directories:
        return 2
    failed = False
    for directory in directories:
        # Each leaf runs independently: equal test basenames cannot shadow one another.
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('wave3_discover.py')),
                                 str(directory)], timeout=150, shell=False)
        failed |= result.returncode != 0
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
