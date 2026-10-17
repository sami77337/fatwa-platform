"""Deterministic fabricated inputs/configuration. Never accepts a caller source map."""
import json
from types import MappingProxyType
from .contracts import PAYLOAD_SCHEMA, SOURCE_IDENTITY

ORIGINAL_QUESTION = '  سُؤَالٌ اصطناعي\tبِعلاماته\nوسطره  '


def synthetic_payload() -> bytes:
    first = dict(external_id='W7-VALID-1', question=ORIGINAL_QUESTION,
                 prepared_clip_url='https://example.invalid/wave7.mp4',
                 reference_links=[dict(source_id='W7-SOURCE', heading_id='W7-HEADING-1')])
    items = [first,
        dict(external_id='W7-MISSING-MEDIA', question='سؤال اصطناعي بلا مقطع'),
        dict(external_id='W7-INVALID-MEDIA', question='سؤال اصطناعي', prepared_clip_url='http://example.invalid/x'),
        dict(first, question='نسخة اصطناعية مكررة'),
        dict(external_id='BAD\tID', question='  سؤال محفوظ  '),
        dict(external_id=73, question=None),
        dict(external_id='W7-READY-2', question=ORIGINAL_QUESTION,
             prepared_clip_url='https://example.invalid/wave7-second.mp4',
             reference_links=[dict(source_id='W7-SOURCE',heading_id='W7-HEADING-2')]), None]
    return json.dumps(dict(schema=PAYLOAD_SCHEMA, synthetic_fixtures_only=True, items=items),
                      ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def trusted_bridge_config():
    from apps.reference_links.bridge import BridgeConfig, EditionMap, HeadingMap, SourceIdentity
    return BridgeConfig(EditionMap(SourceIdentity(**SOURCE_IDENTITY), 7001), tuple(
        HeadingMap('W7-SOURCE', f'W7-HEADING-{row}', f'wave7-title-{row}', row) for row in (1, 2, 3)))


def trusted_reference_map():
    from apps.fatwa_drafts.intake import ReferenceLink
    from apps.prepared_pipeline import C1Pointer, ExplicitMapping
    return MappingProxyType({C1Pointer('W7-SOURCE', f'W7-HEADING-{row}'): ExplicitMapping(
        ReferenceLink(**SOURCE_IDENTITY, source_id=f'wave7-title-{row}'), 7001, row,
        'Wave7 fixed fabricated fixture; pins are caller assertions, not an archive inspection')
        for row in (1, 2, 3)})


def seed_reference_catalog(*, synthetic_fixtures_only: bool = False) -> int:
    """Idempotent fixed synthetic fixture, never discovers/repairs an occupied source."""
    from apps.reference.models import ReferenceWork, ReferenceEdition, ReferenceHeading
    from apps.reference.normalization import normalize_title
    from .contracts import ContractError
    from .guards import synthetic_atomic

    def exact(model, pk, values):
        instance, created = model.objects.get_or_create(pk=pk, defaults=values)
        if not created and any(getattr(instance,key) != value for key,value in values.items()):
            raise ContractError('fixture: occupied_identity_mismatch')
        return instance

    with synthetic_atomic(synthetic_fixtures_only=synthetic_fixtures_only):
        exact(ReferenceWork,7001,dict(source_namespace=SOURCE_IDENTITY['source_namespace'],
            source_book_id='622',title_original='مرجع اصطناعي لتجارب Wave7',madhhab='اصطناعي فقط'))
        exact(ReferenceEdition,7001,dict(work_id=7001,edition_key=SOURCE_IDENTITY['edition_key'],
            title='طبعة اصطناعية',publisher='ناشر اصطناعي',
            source_archive_sha256=SOURCE_IDENTITY['source_archive_sha256'],
            source_input_sha256=SOURCE_IDENTITY['source_input_sha256'],ingest_checksum='c'*64,
            input_name='wave7-fixed-fabricated-fixture',heading_count=3,root_count=1,max_depth=2))
        for row,title in [(1,'كِتَابٌ اصطناعي'),(2,'بابٌ اصطناعي أول'),(3,'بابٌ اصطناعي ثان')]:
            exact(ReferenceHeading,7000+row,dict(edition_id=7001,source_id=f'wave7-title-{row}',
                source_row_id=row,parent_id=None if row==1 else 7001,source_order=row,
                position=1 if row==1 else row-1,depth=1 if row==1 else 2,
                source_page_id=row,source_part='الأول',source_page_number=6+row,
                source_entry_number=None,title_original=title,title_normalized=normalize_title(title)))
    return 7001
