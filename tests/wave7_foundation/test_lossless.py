"""Approved lossless numeric/source-slice contract; pure, no database."""
from decimal import Decimal
import hashlib
import json
import sys
import unittest

from apps.intake_workflow import contracts as c


class LosslessContractTests(unittest.TestCase):
    def test_exponent_beyond_c_decimal_layout_still_has_an_exact_decimal_value(self):
        raw=(b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
             b'"items":[1e-999999999999999999999999]}')
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        value=parsed.items[0]
        self.assertTrue(value.is_finite())
        self.assertEqual(value.as_tuple().digits,(1,))
        self.assertEqual(value.as_tuple().exponent,-999999999999999999999999)
        self.assertIn(b'1e-999999999999999999999999',parsed.prepared_bytes())
        digits='9'*6000
        raw=raw.replace(b'999999999999999999999999',digits.encode())
        value=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True).items[0]
        self.assertEqual(value.as_tuple().exponent,-int(Decimal(digits)))

    def test_integer_at_exact_one_million_byte_envelope_bound_is_not_rejected(self):
        prefix=b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":['
        suffix=b']}'
        digits=b'9'*(c.MAX_INPUT_BYTES-len(prefix)-len(suffix))
        raw=prefix+digits+suffix
        parsed=c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        self.assertIs(type(parsed.items[0]),int)
        self.assertEqual(parsed.item_sources[0].text.encode(),digits)
        self.assertIn(digits,parsed.prepared_bytes())
        with self.assertRaises(c.ContractError):
            c.parse_synthetic_payload(raw+b' ',synthetic_fixtures_only=True)

    def test_fraction_underflow_and_large_integer_keep_value_and_numeric_tokens(self):
        digits = b'9' * 6000
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
               b'"items":[{"external_id":73.000000000000001,"question":1e-20000},' + digits + b']}')
        before = sys.get_int_max_str_digits()
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        self.assertEqual(parsed.items[0]['external_id'],Decimal('73.000000000000001'))
        self.assertEqual(parsed.items[0]['question'],Decimal('1e-20000'))
        self.assertIs(type(parsed.items[1]),int)
        self.assertEqual(str(Decimal(parsed.items[1])),digits.decode())
        prepared = parsed.prepared_bytes()
        self.assertIn(b'73.000000000000001',prepared)
        self.assertIn(b'1E-20000',prepared.upper())
        self.assertIn(digits,prepared)
        values = json.loads(prepared,parse_float=Decimal,parse_int=lambda token:int(Decimal(token)))
        self.assertEqual(values['items'],list(parsed.items))
        self.assertEqual((parsed.raw,parsed.payload_sha256),(raw,hashlib.sha256(raw).hexdigest()))
        self.assertEqual(sys.get_int_max_str_digits(),before)

    def test_exact_utf8_sources_have_absolute_half_open_byte_offsets(self):
        row = '{ "external_id": 73.000000000000001, "question":"  سُؤَال\\t\\n  ", "reference_links": [ {"unknown":1e-20000}, null ] }'
        raw = (' \r\n{"schema":"fatwa.wave7.synthetic-intake.v1", "synthetic_fixtures_only":true, '
               '"items": [ '+row+', '+row+' ]}\t').encode()
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        self.assertEqual(len(parsed.item_sources),2)
        self.assertEqual(len(parsed.reference_sources[0]),2)
        first,second = parsed.item_sources
        self.assertEqual(first.text,row)
        self.assertEqual(second.text,row)
        self.assertLess(first.end,second.start)
        for source in (*parsed.item_sources,*parsed.reference_sources[0],*parsed.reference_sources[1]):
            self.assertEqual(raw[source.start:source.end],source.text.encode('utf-8'))
        for item,refs in zip(parsed.item_sources,parsed.reference_sources):
            for pointer in refs:
                self.assertGreaterEqual(pointer.start,item.start)
                self.assertLessEqual(pointer.end,item.end)
        self.assertEqual(parsed.reference_sources[0][0].text,'{"unknown":1e-20000}')
        self.assertEqual(parsed.reference_sources[0][1].text,'null')

    def test_escaped_member_names_and_malformed_rows_keep_exact_source(self):
        raw = (b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,'
               b'"it\\u0065ms":[null,73.000000000000001,{"ref\\u0065rence_links":[true,{}]},'
               b'{"reference_links":"invalid"}]}')
        parsed = c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
        self.assertEqual([s.text for s in parsed.item_sources[:2]],['null','73.000000000000001'])
        self.assertEqual([s.text for s in parsed.reference_sources[2]],['true','{}'])
        self.assertEqual(parsed.reference_sources[3],())

    def test_numeric_change_preserves_duplicate_unicode_and_envelope_rejections(self):
        for raw in (b'{"schema":1,"schema":2}',b'\xff',
            b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":["\\ud800"]}',
            b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":["\\u0000"]}',
            b'{"schema":"fatwa.wave7.synthetic-intake.v1","synthetic_fixtures_only":true,"items":[NaN]}'):
            with self.subTest(raw=raw),self.assertRaises(c.ContractError):
                c.parse_synthetic_payload(raw,synthetic_fixtures_only=True)
