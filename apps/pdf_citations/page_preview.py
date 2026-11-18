"""Bounded isolated single-page PDF derivative for private human verification.

No file is read from disk or sent externally. The current caller MUST establish
the PDF's case/source identity and READ_MEDIA/CITE rights before invoking this.
The isolated worker validates the original again, and this parent checks the
returned page identity, bounds and format before use.
"""

import base64
import json
import subprocess
import sys

MAX_ORIGINAL_BYTES = 192000
MAX_DERIVED_BYTES = 262144
MAX_WORKER_STDOUT = 400000


class PdfPageUnavailable(ValueError):
    """Fixed denial code: never reveal parser errors or private source bytes."""


def selected_page(raw: bytes, *, page_number: int, page_count: int) -> bytes:
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_ORIGINAL_BYTES
        or type(page_number) is not int
        or type(page_count) is not int
        or not 1 <= page_number <= page_count <= 10
    ):
        raise PdfPageUnavailable("pdf_page_selection_invalid")
    request = json.dumps(
        {
            "raw": base64.b64encode(raw).decode("ascii"),
            "page_number": page_number,
            "page_count": page_count,
        },
        separators=(",", ":"),
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "apps.pdf_citations.page_worker"],
            input=request,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=6,
            check=False,
        )
        if result.returncode or len(result.stdout) > MAX_WORKER_STDOUT:
            raise ValueError
        value = json.loads(result.stdout)
        if (
            type(value) is not dict
            or set(value) != {"page_number", "page_count", "pdf"}
            or type(value["page_number"]) is not int
            or type(value["page_count"]) is not int
            or value["page_number"] != page_number
            or value["page_count"] != 1
            or type(value["pdf"]) is not str
        ):
            raise ValueError
        page = base64.b64decode(value["pdf"], validate=True)
        if not 1 <= len(page) <= MAX_DERIVED_BYTES:
            raise ValueError
        if not page.startswith(b"%PDF-") or not page.rstrip().endswith(b"%%EOF"):
            raise ValueError
        return page
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
        raise PdfPageUnavailable("pdf_page_derivative_unavailable") from exc
