"""Actual producer calls in a new process, strictly outside HTTP and outer atomic."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.wave7_test"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "replay", "start-review"])
    parser.add_argument("--key")
    parser.add_argument("--item")
    args = parser.parse_args()
    import django
    django.setup()
    from target import select_existing_test_database
    select_existing_test_database()
    if args.action == "inspect":
        from process_probe import inspect_batch
        result = inspect_batch(args.key)
    elif args.action == "replay":
        from apps.intake_workflow.models import IntakeBatch, IntakeItem, IntakeReference, ReviewEvent
        from apps.intake_workflow.intake import import_intake
        batch = IntakeBatch.objects.get(idempotency_key=args.key)
        models = (IntakeBatch, IntakeItem, IntakeReference, ReviewEvent)
        before = tuple(model.objects.count() for model in models)
        receipt = import_intake(bytes(batch.original_payload), idempotency_key=args.key,
                                synthetic_fixtures_only=True)
        assert receipt.batch_id == batch.id and receipt.decision.value == "REPLAY"
        assert tuple(model.objects.count() for model in models) == before
        result = receipt.report()
    else:
        from apps.intake_workflow.review import transition_review, ReviewConflict
        try:
            result = asdict(transition_review(args.item, operation_id=uuid4(), action="start_review",
                expected_status="UNREVIEWED", reason="E6 synthetic browser race", synthetic_fixtures_only=True))
        except ReviewConflict as error:
            print(json.dumps(dict(code=error.code, status_code=error.status_code)))
            return 3
    print(json.dumps(result, default=str, ensure_ascii=False))  # metadata/source strings only
    return 0


if __name__ == "__main__":
    sys.exit(main())
