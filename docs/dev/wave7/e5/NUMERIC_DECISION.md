# Numeric representation decision required — no adoption

Independent review reproduced this accepted malformed row failing storage:

```json
{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":[{"external_id":73.000000000000001,"question":"  original  "}]}
```

Current parse_synthetic_payload returns Python float `73.0`. PostgreSQL JSONB
derives the original exact numeric value `73.000000000000001`; the item source
check correctly rejects the rounded row and rolls back. That source check must
not be weakened. The original numeric ID is invalid as an ID, but its original
row should persist with external_id=NULL, as required by the contract.

## Concrete local proposal, not published as executable code

1. Parse fractional/exponent JSON numbers with Decimal; retain integer tokens as
   int. Thus ParsedPayload.items changes its runtime fractional values from float
   to Decimal, while its tuple[object,...] signature remains the same.
2. Add a pure stdlib JSON encoder/decoder. Encode finite Decimal as numeric JSON
   tokens, never as strings or rounded floats. ParsedPayload.prepared_bytes()
   retains the numeric value; original_payload/raw/hash retain exact lexical bytes.
3. Configure the existing payload_snapshot, original_row and original_pointer
   JSONFields with that encoder/decoder, using an additive migration 0004. Reads
   would return Decimal fractional values. Database column types would remain
   JSONB. E1/E3 would need to persist source values from the lossless parsed rows
   and use this codec for source serialization instead of a default float decoder.
4. Runtime statuses, scope, fixed maps, ordinals and source equality do not change.

A local implementation draft and regression were preserved under
`/tmp/fatwa-wave7-e5-evidence/numeric-contract-proposal/` and
`numeric-contract-proposal.patch`; they are deliberately absent from executable
code, migrations and registered test suites in this corrective increment.
This is **not** a numeric fix or a numeric PASS claim. The failing reproductions
remain in the review RED logs. No expected-failure decorator or optional PASS
fallback was introduced to hide them.

## Remaining representation ambiguity

Decimal plus JSONB alone cannot preserve every formerly accepted number.
For example Python's old float decoder accepts `1e-20000` as 0.0, while exact
PostgreSQL JSONB cannot hold that value. PostgreSQL numeric has a fractional
limit of 16383 digits and an integral limit of 131072 digits.
Sources: [numeric limits](https://www.postgresql.org/docs/17/datatype-numeric.html),
[JSONB numeric restrictions](https://www.postgresql.org/docs/17/datatype-json.html).

Leadership must choose a lossless representation for those values (which would
change the frozen storage contract), or explicitly authorize a documented input
restriction. Neither a new rejection of formerly accepted rows nor a weaker
source comparison has been adopted. The numeric part is on hold pending that
decision; the three independent integrity fixes can be reviewed now.

No schema/interface freeze or dependent write dispatch until resolution and
fresh independent acceptance. GATES_HOLD / NOT_DEPLOYED.
