import json
import unittest
from dataclasses import asdict, FrozenInstanceError, replace
from unittest.mock import patch
from apps.reference_links.bridge import *
from apps.reference_links.demo import fixtures, main
from apps.reference_links.resolution import SnapshotCatalog, Outcome
from apps.fatwa_drafts.intake import ReferenceLink
from tools.content_intake.cli import normalize

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.config, self.heading = fixtures()
        self.pointer = {'source_id': 'source-X', 'heading_id': 'heading-Y'}

    def run_links(self, links=None, heading=None, config=None):
        raw = json.dumps({'schema':'fatwa.prepared-intake.v1','items':[
            {'external_id':'x','question':'ignored','reference_links': links if links is not None else [self.pointer]}]}).encode()
        return resolve_prepared_pointers(raw, config or self.config,
            SnapshotCatalog((heading or self.heading,)))[0].reference_links

    def test_c1_real_shape(self):
        items, _ = normalize([{'external_id':'x','question':'q','reference_links':[self.pointer]}])
        self.assertEqual(self.run_links(items[0]['reference_links'])[0].status, Outcome.VERIFIED)

    def test_c2_real_shape(self):
        link = ReferenceLink(**asdict(self.config.edition.identity), source_id='row-Z')
        result = self.run_links([asdict(link)])[0]
        self.assertEqual(result.status, Outcome.VERIFIED)
        self.assertEqual(dict(result.original_pointer), asdict(link))

    def test_no_numeric_conversion(self):
        self.assertEqual(self.run_links([{'source_id':'41','heading_id':'73'}])[0].status, Outcome.UNVERIFIED)

    def test_no_map(self):
        self.assertEqual(self.run_links(config=replace(self.config, headings=()))[0].status, Outcome.UNVERIFIED)

    def test_sha_and_all_c2_pins(self):
        for key in asdict(self.config.edition.identity):
            link = dict(asdict(self.config.edition.identity), source_id='row-Z')
            link[key] = 'c'*64 if key.endswith('sha256') else 'different'
            self.assertEqual(self.run_links([link])[0].reasons, ('source_identity_mismatch',))

    def test_catalog_sha(self):
        result = self.run_links(heading=replace(self.heading, source_input_sha256='c'*64))[0]
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.citation)

    def test_catalog_book_namespace(self):
        for key in ('source_namespace','source_book_id'):
            self.assertEqual(self.run_links(heading=replace(self.heading, **{key:'wrong'}))[0].status, Outcome.UNVERIFIED)

    def test_cross_edition(self):
        self.assertEqual(self.run_links(heading=replace(self.heading, edition_id=42))[0].status, Outcome.NOT_FOUND)

    def test_user_defined_edition(self):
        config = replace(self.config, edition=replace(self.config.edition, edition_id=987))
        self.assertEqual(self.run_links(config=config, heading=replace(self.heading, edition_id=987))[0].status, Outcome.VERIFIED)

    def test_missing_location(self):
        result = self.run_links(heading=replace(self.heading, printed_page=None))[0]
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.citation)

    def test_arabic_citation(self):
        citation = self.run_links()[0].citation
        for value in ('كشاف القناع', 'كتاب الطهارة / باب الطهارة', 'ج الأول', 'ص 12', 'وليس نص فتوى'):
            self.assertIn(value, citation)
        for value in ('human-edition-A', 'synthetic-only', 'edition_id', 'publisher'):
            self.assertNotIn(value, citation)

    def test_markup(self):
        heading = replace(self.heading, work_title='<script>"&</script>')
        citation = self.run_links(heading=heading)[0].citation
        self.assertIn('&lt;script&gt;&quot;&amp;', citation)
        self.assertNotIn('<script>', citation)
        self.assertEqual(citation, self.run_links(heading=heading)[0].citation)

    def test_duplicate_mappings(self):
        h = self.config.headings[0]
        for other in (h, replace(h,c2_source_id='other',source_row_id=74),
                      replace(h,c1_heading_id='other',source_row_id=74),
                      replace(h,c1_heading_id='other',c2_source_id='other')):
            with self.assertRaises(ValueError):
                replace(self.config, headings=(h,other))

    def test_duplicate_pointers(self):
        self.assertEqual(self.run_links([self.pointer,self.pointer])[1].reasons, ('duplicate_pointer',))

    def test_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.config.edition.edition_id = 2
        with self.assertRaises(ValueError):
            replace(self.config, headings=list(self.config.headings))

    def test_bad_numeric_configuration(self):
        for value in ('41',True,0,-1,2**63):
            with self.assertRaises(ValueError):
                replace(self.config.edition, edition_id=value)
            with self.assertRaises(ValueError):
                replace(self.config.headings[0], source_row_id=value)

    def test_invalid_pin(self):
        for value in ('A'*64,'bad','b'*63):
            with self.assertRaises(ValueError):
                replace(self.config.edition.identity, source_input_sha256=value)

    def test_absent_references_no_lookup(self):
        class NoCalls:
            def lookup(self,*args):
                raise AssertionError('unexpected catalog lookup')
        raw = b'{"schema":"fatwa.prepared-intake.v1","items":[{"external_id":"x","question":"heading-Y"}]}'
        self.assertEqual(resolve_prepared_pointers(raw,self.config,NoCalls())[0].reference_links, ())

    def test_ambiguous_catalog(self):
        raw = json.dumps({'schema':'fatwa.prepared-intake.v1','items':[{'external_id':'x','reference_links':[self.pointer]}]}).encode()
        result = resolve_prepared_pointers(raw,self.config,SnapshotCatalog((self.heading,self.heading)))[0].reference_links[0]
        self.assertEqual(result.status, Outcome.AMBIGUOUS)
        self.assertIsNone(result.citation)

    def test_no_network_or_writes(self):
        with patch('builtins.open', side_effect=AssertionError('file I/O')), patch('socket.socket', side_effect=AssertionError('network')):
            self.assertEqual(self.run_links()[0].status, Outcome.VERIFIED)
            with patch('builtins.print'):
                main()

    def test_bad_envelope(self):
        for raw in (b'[]',b'\xff',b'{"schema":"x","schema":"y"}'):
            with self.assertRaises(ValueError):
                resolve_prepared_pointers(raw,self.config,SnapshotCatalog(()))

if __name__ == '__main__':
    unittest.main()
