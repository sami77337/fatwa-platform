# Offline Arabic text quality inspection

Development only; fabricated questions and revision text only. No database,
network, source writes, grants, scholarly approvals, or publication. No dependency
installation beyond the repository's Python 3.13 interpreter is needed.

From the repository root:

```powershell
python -m tools.arabic_text_quality --synthetic-only --input tools/arabic_text_quality/fixtures/question.txt
python -m tools.arabic_text_quality --synthetic-only --before tools/arabic_text_quality/fixtures/question.txt --input tools/arabic_text_quality/fixtures/revision.txt --kind revision
python -m tools.arabic_text_quality --synthetic-only --input tools/arabic_text_quality/fixtures/revision.txt --fail-on warning
python -m unittest discover -s tests/arabic_text_quality
```

`--input` is the inspected text (the after text when `--before` is supplied).
`--kind question|revision` labels its purpose; both kinds use the same checks.
`--synthetic-only` is a required operator attestation, not a private-data detector.
Use only invented text. No original owner source archives are used.

Input is a local regular UTF-8 file, bounded to 40,000 bytes and 10,000 Unicode
code points per file. Invalid UTF-8 and surrogate code points are rejected.
The reader preserves CRLF, CR, LF, and a UTF-8 BOM. It rejects network paths,
symlinks, junctions, and non-regular files. Input files are opened only for reading.

Stdout contains one deterministic ASCII-escaped JSON report, including exact
source strings, SHA-256 hashes of their UTF-8 bytes, runtime Unicode version,
diagnostic severities, original code points and locations. JSON parsing restores
the exact original text; escapes keep control characters from acting on terminals.
No timestamps or local paths enter the report. See the
[service contract](../../apps/arabic_text_quality/README.md) for offsets, check
semantics, and limits. Determinism assumes the same Python Unicode database.

Exit status is `0` after successful inspection by default, including when findings
exist; `1` when `--fail-on info|warning|error` matches a finding at or above the
threshold; `2` on invalid arguments, missing synthetic attestation, or invalid input.
Errors use fixed codes on stderr without echoing paths or source contents.
The CLI has no fix, overwrite, upload, or output-file option. Redirect stdout to a
separate report path when needed; never redirect it onto an input file.

The fixtures are invented technical questions with no case data or scholarly
answer. They demonstrate a repeated-space change and an Arabic presentation-form
character; reported differences need human interpretation and are never applied.

NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED;
U03/U10 OWNER_APPROVAL_PENDING. A quality report cannot advance any gate.
