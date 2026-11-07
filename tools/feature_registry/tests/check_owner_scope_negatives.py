"""Run three read-only regression checks using an explicit local source directory."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_owner_scope as scope


def expect_failure(label, message, operation):
    try:
        operation()
    except ValueError as exc:
        if str(exc) != message:
            raise
        print("PASS", label)
    else:
        raise RuntimeError("Unexpected success: " + label)


def run(root):
    scope.verify(root)  # Authenticate the six originals before testing mutations.
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp)
        (copied / scope.OWNER).write_bytes((root / scope.OWNER).read_bytes() + b"x")
        expect_failure("modified DOCX", "Source pin mismatch: " + scope.OWNER, lambda: scope.verify(copied))

    paragraphs = scope.owner_paragraphs((root / scope.OWNER).read_bytes())
    lines = (root / scope.SPEC).read_text(encoding="utf-8-sig").splitlines()
    clauses = [json.loads(line) for line in (root / scope.REGISTRY).read_bytes().splitlines()]
    forward = json.loads((root / scope.FORWARD).read_bytes())["records"]
    reverse = json.loads((root / scope.REVERSE).read_bytes())["records"]
    expect_failure("missing owner row", "Missing or duplicate owner paragraph",
                   lambda: scope.audit_records(paragraphs, lines, clauses, forward[:-1], reverse))
    reverse[0]["original_point_origins"].pop()
    expect_failure("missing reverse link", "Forward/reverse relationship mismatch",
                   lambda: scope.audit_records(paragraphs, lines, clauses, forward, reverse))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    run(parser.parse_args().source_root.resolve())
