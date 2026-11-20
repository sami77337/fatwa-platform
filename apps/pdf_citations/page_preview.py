"""Bounded isolated single-page PDF derivative for private human verification.

No file is read from disk or sent externally. The current caller MUST establish
the PDF's case/source identity and READ_MEDIA/CITE rights before invoking this.
The isolated worker validates the original again, and this parent checks the
returned page identity, bounds and format before use.
"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

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
        process = subprocess.Popen(
            [sys.executable, "-m", "apps.pdf_citations.page_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parents[2],
            env={
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
            },
        )
        captured = bytearray()
        overflow = threading.Event()

        def drain_stdout():
            # Drain concurrently to prevent a full pipe from blocking the child.
            # Retain at most the configured ceiling plus one byte in memory.
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    return
                remaining = MAX_WORKER_STDOUT + 1 - len(captured)
                if remaining > 0:
                    captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()

        reader = threading.Thread(target=drain_stdout, daemon=True)
        reader.start()
        try:
            process.stdin.write(request.encode("utf-8"))
            process.stdin.close()
            returncode = process.wait(timeout=6)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()
            reader.join(timeout=1)
            raise
        reader.join(timeout=1)
        if reader.is_alive():
            process.kill()
            process.wait()
            process.stdout.close()
            reader.join(timeout=1)
            raise ValueError
        if returncode != 0 or overflow.is_set() or len(captured) > MAX_WORKER_STDOUT:
            raise ValueError
        response = bytes(captured)
        value = json.loads(response.decode("utf-8"))
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
