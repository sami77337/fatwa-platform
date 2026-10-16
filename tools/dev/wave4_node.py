"""Node test runner with fail-closed TAP collection guard."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main(files=None):
    files = sys.argv[1:] if files is None else files
    if not files:
        return 2
    with tempfile.TemporaryFile() as stream:
        try:
            result = subprocess.run(["node", "--test", "--test-reporter=" + (Path(__file__).with_name("wave4_reporter.mjs").as_uri()), *files],
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=150,
                                    shell=False)
        except subprocess.TimeoutExpired:
            return 124
        except OSError:
            return 127
        stream.seek(0)
        count = 0
        for line in stream:
            match = re.fullmatch(rb"D6_REGISTERED_TESTS=(\d+)\s*", line)
            if match:
                count = int(match[1])
            # Bounded lines, retaining failures in enclosing runner's tail.
            print(line[:2000].decode("utf-8", errors="replace"), end="")
        return 1 if result.returncode else (0 if count else 2)


if __name__ == "__main__":
    raise SystemExit(main())

