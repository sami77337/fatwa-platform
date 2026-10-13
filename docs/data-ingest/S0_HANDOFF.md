# S1 → S0 integration contract

**Local development handoff. NOT_DEPLOYED / GATES_HOLD / Phase01 BLOCKED.**
No S0 models, migrations, settings, endpoints or root dependencies were changed.
The artifact is one book's heading index, not substantive rulings or a global
taxonomy. U03/U10 remain pending; historical permission rows remain non-granting.

## Python API

~~~python
from tools.fiqh_import import ingest, load_manifest, write_export

manifest = load_manifest("docs/data-ingest/owner-622-r1-jsonl.manifest.json")
result = ingest(
    "tests/fiqh_import/.scratch/owner-622-r1.jsonl",
    manifest,
    profile="real-622",
    input_adapter="owner-622-r1",
)
assert result.report["valid"] is True
assert result.report["real_source_acceptance"] == "STRUCTURE_VALIDATED"
write_export(result, "reviewed-output.jsonl")
~~~

This example has not executed here because Python is unavailable. The manifest
pins the actual observed owner JSONL. For CSV/nested JSON use its actual member
hash, member identity and matching provenance instead; the edition adapter checks
all three known format pins. The acceptance tests do this without adding raw data
to git.

Manifest is frozen and typed. ImportResult contains report and output_bytes.
Strict failures raise ValidationError carrying .report. Diagnostic strict=False
returns an invalid report with output_bytes=None. write_export rejects invalid
results or hash mismatch. Malformed formats/manifests raise IngestError; I/O may
raise OSError. The CLI guards source/manifest/output aliases; API callers must
choose safe artifact destinations. There is no database adapter or streaming
database import.

## Output fields

The [JSON Schema](../../tools/fiqh_import/schemas/output-heading.schema.json)
uses draft 2020-12 and additionalProperties=false. Every normalized row includes
every field, with explicit nulls or an empty source_metadata object as appropriate.

| Fields | Meaning |
| --- | --- |
| contract_version, reference_kind | Exactly fiqh-toc.v1, book_heading_index. |
| dataset_id, book_id, source_kind | Fixture namespace, "622", synthetic/owner_supplied. |
| source_id, parent_id | Canonical string IDs; null root parent. Original owner types remain in source_metadata. |
| title, search_title | Original display title and separate derived search helper. Escape source text in HTML. |
| sibling_order, sequence, depth | Original sibling order, 1-based parent-first sequence, root depth 1. |
| part, page | Part is a positive integer or the preserved named introductory label "المقدمة"; page is a positive integer. |
| source_part, source_page | Original printed reference representation, including numeric-string padding. |
| edition, provenance | Original overrides or pinned manifest values. |
| title_origin, inference_evidence | Direct/inferred distinction; supplied evidence is mandatory when inferred. |
| root_kind | null/introduction/fiqh_book; classifications are confined to this edition's roots. |
| input_sha256, input_record | Exact raw input hash, 1-based logical record position; CSV header excluded. |
| source_metadata | Original owner ID/parent types, page IDs, title keys, source depth/count/leaf flags and paths where supplied. Canonical inputs use {}. |

Named part labels must not be coerced into fabricated numeric parts by S0.
Source page IDs must not be confused with printed page numbers. Preserve the
fixture namespace so reference IDs cannot collide with fatwa IDs.

Schemas describe individual rows. Cross-row uniqueness, parent existence,
reachability, ordering, root classification and completeness need the validator.

## Source evidence and consumer requirements

The archive SHA256 was actually verified against the owner's pin. Independent
Node checks matched all 11,397 ID/title pairs against the archive's original-title
CSV and confirmed CSV/nested JSON consistency, roots, depth, reachability,
sibling order and printed references. See [source inspection](source-inspection.json).
These checks do not substitute for Python importer tests. Normalized output hash,
Python rerun stability and Python acceptance remain NOT_RUN.

The supplied CSV/JSONL titles are direct original-index labels, with key prefix
622-. The nested JSON contains the same independently matched names. The adapter
pins the observed members, preserves their text and rejects unknown fields.
Archive code was treated as data and was not executed. Upstream 622.db/title.zip
hashes are declared metadata only; those upstream files were not supplied.

S0 should verify contract version, valid report, fixture identity and exact output
hash before any persistence. Keep synthetic fixtures visibly identified.
A future S0 adapter can consume parent-first rows and perform its own atomic,
idempotent import keyed by dataset/source identity. This handoff does not authorize
that adapter, migrations, production activation, permission grants or publication.

PostgreSQL integration, Django checks and query performance are NOT_RUN in S1
and remain outside its ownership. Standalone source validation has no PostgreSQL
dependency.
