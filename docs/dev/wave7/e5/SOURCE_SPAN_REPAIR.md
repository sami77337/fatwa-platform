# Source span INSERT performance repair

Leadership authorized this limited local repair after fresh reviewer evidence on
tree `606baccdfa67d7b89af7d3f35d385fe239db24d2`. Publication and source/product
acceptance remain on hold. No owner archive or catalog is involved.

The unchanged baseline fails to persist a valid 1,000,000-byte synthetic batch
containing 800 rows and references on PostgreSQL 17.11 and 18.6. Each item INSERT
row trigger reparses its entire parent array and searches from the first element
to its ordinal. Repeated suffix copies add further work. Both engines cancel an
item INSERT under the existing three-second statement timeout; the outer intake
transaction rolls back. The previous seven-probe result (five PASS, two ERROR) is
preserved separately. The corrected reviewer catalog probes pass three of three
on that unchanged baseline; the immutable-catalog UPDATE was a fixture error.

Migration `0005_statement_source_spans` adds a statement trigger with a PostgreSQL
INSERT transition relation. For each distinct parent batch actually inserted by
that statement, it reads the immutable raw payload once, parses the item array
once and advances through exact token lengths and JSON delimiters. It then checks
each inserted row's structural ordinal, byte range, original token, question and
opaque external ID. Source text uses `json`, never numeric conversion or JSONB.
Arrays of offsets are local to the trigger invocation, bounded by the existing
1,000-row envelope. There is no persistent/session cache or caller-supplied index.

Validation still runs before the INSERT statement can complete. Any bad row
rejects that entire statement, and the existing outer transaction still rolls back
the batch and children. The BEFORE ROW write guard, immutable originals, pointer
checks, ownership checks, byte/row/reference limits, raw SHA checks and database
timeouts are unchanged. Historical migrations 0001–0004 and `intake.py` are
unchanged. Reversing 0005 restores the previous row trigger without modifying data.

Five permanent PostgreSQL regressions cover the exact million-byte/800-row case,
all 1,000 accepted rows, 1,000,001-byte and 1,001-row refusal both before SQL and at
storage, reordered sparse multi-batch insertion, and a matching shadow token that
must reject every inserted row atomically. They record actual import and largest
item-INSERT durations and assert the real Django connection still reports `3s`.
The existing matrix now includes their explicit module: 115 existing cases plus
five new cases, for 120 required cases. DB labels remain outside port-1 runners.

With a newly created, guarded synthetic database and the existing Python 3.13
environment, the commands are:

```sh
python manage.py test tests.wave7_foundation.test_span_performance_db --noinput --verbosity=2 --settings=config.settings.wave7_test
python tools/dev/wave7_qa.py --suite database --json "$OUT/wave7-database.json"
```

The reviewer v2 file stays outside the product checkout, unchanged at SHA256
`04106c31671ca727b0fc5bc27c9aba0a065a90981b7e21744604f59a521510af`.
Its complete nine-case suite is also required on both engines. Exact commands,
head/tree, role/OID/marker/version, allowed flags, stdout/stderr, timing, counts,
hashes and exact-resource cleanup are retained in the separate evidence handoff.
Producer-hosted execution does not replace the reviewer's adjudication.

Windows, protected-browser acceptance, real-source acceptance and deployment are
separate gates. **NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED**.
