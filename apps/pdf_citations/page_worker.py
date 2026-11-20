"""PDF single-page renderer in a CPU/memory-bounded parser subprocess.

This output is a one-page derivative, *not* a modification to the original.
Source and output are both checked against the same restrictive PDF validator.
"""

import base64
import io
import json
import sys

from apps.private_media.worker import _pdf

from .page_preview import MAX_DERIVED_BYTES, MAX_ORIGINAL_BYTES


def produce(raw: bytes, page_number: int, expected_pages: int) -> bytes:
    from pypdf import PdfReader, PdfWriter

    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_ORIGINAL_BYTES
        or type(page_number) is not int
        or type(expected_pages) is not int
        or not 1 <= page_number <= expected_pages <= 10
        or _pdf(raw) != {"pages": expected_pages, "active_content": False}
    ):
        raise ValueError
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) != expected_pages:
        raise ValueError
    writer = PdfWriter()
    # The selected page is physically the ONLY page in the returned PDF.
    # Do not carry annotations, extra actions, comments or document metadata.
    writer.add_page(
        reader.pages[page_number - 1],
        excluded_keys=("/Annots", "/AA", "/B", "/Metadata"),
    )
    target = io.BytesIO()
    writer.write(target)
    derivative = target.getvalue()
    if (
        not 1 <= len(derivative) <= MAX_DERIVED_BYTES
        or _pdf(derivative) != {"pages": 1, "active_content": False}
    ):
        raise ValueError
    return derivative


def main():
    try:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except ImportError:
            pass
        value = json.loads(sys.stdin.read(300000))
        if type(value) is not dict or set(value) != {"raw", "page_number", "page_count"}:
            raise ValueError
        raw = base64.b64decode(value["raw"], validate=True)
        selected = produce(raw, value["page_number"], value["page_count"])
        sys.stdout.write(
            json.dumps(
                {
                    "pdf": base64.b64encode(selected).decode("ascii"),
                    "page_number": value["page_number"],
                    "page_count": 1,
                },
                separators=(",", ":"),
            )
        )
        return 0
    except Exception:
        # Nothing about private bytes or parser failures goes to stderr/stdout.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
