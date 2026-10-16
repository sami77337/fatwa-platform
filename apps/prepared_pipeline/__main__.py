"""Run the inline synthetic example, without reading or saving staff files."""
import argparse
import json
import sys
from . import prepare_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Deterministic machine report')
    args = parser.parse_args()
    raw = json.dumps({'schema': 'fatwa.prepared-intake.v1', 'items': [
        {'external_id': 'synthetic-001', 'question': 'سؤال تجريبي بلا جواب أو حكم',
         'prepared_clip_url': 'https://example.invalid/finished-synthetic.mp4',
         'reference_links': [{'source_id': 'synthetic-source', 'heading_id': 'synthetic-heading'}]},
        {'external_id': 'synthetic-002', 'question': 'سؤال تجريبي ينتظر رابط المقطع'}
    ]}, ensure_ascii=False).encode('utf-8')
    batch = prepare_batch(raw, synthetic_fixtures_only=True)
    sys.stdout.buffer.write(batch.json_bytes() if args.json else
                            (batch.preview_ar() + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
