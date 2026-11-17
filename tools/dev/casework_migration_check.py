"""Verify populated synthetic cases survive integrity-guard rollback/reapply.

This checks the non-destructive 0002 -> 0001 -> 0002 boundary. Rolling the
initial schema back to zero intentionally removes its tables and is a separate
empty-schema CI check, never a data-preservation promise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import django

    django.setup()
    from django.core.management import call_command
    from django.core.serializers.json import DjangoJSONEncoder
    from django.db import IntegrityError, connection, transaction
    from django.utils import timezone

    from apps.casework import services
    from apps.casework.models import (
        AnswerRevision,
        Case,
        CaseDecision,
        CaseEvent,
        CaseEvidence,
        CaseSource,
    )
    from apps.delivery_queue.models import (
        RequesterTrackingCase,
        RequesterTrackingEvent,
        RequesterTrackingToken,
    )
    from apps.intake_workflow.guards import require_synthetic_write
    from apps.mufti_review.identity import MuftiIdentity, MuftiIdentityProvider

    report = {"status": "ERROR", "deployment": "NOT_DEPLOYED",
              "acceptance": "ACCEPTANCE_HOLD", "boundary": "0002 -> 0001 -> 0002"}
    output = ROOT / ".local/qa/v6-casework/populated-migrations-result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    models = (
        Case, CaseSource, CaseEvidence, AnswerRevision, CaseDecision, CaseEvent,
        RequesterTrackingCase, RequesterTrackingEvent, RequesterTrackingToken,
    )

    def snapshot():
        rows = {model._meta.label: list(model.objects.order_by("pk").values())
                for model in models}
        encoded = json.dumps(rows, cls=DjangoJSONEncoder, sort_keys=True, ensure_ascii=False)
        return encoded, {label: len(items) for label, items in rows.items()}

    def guards():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relname,t.tgname,t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname=ANY(%s) "
                "AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
                [[model._meta.db_table for model in models[:6]]],
            )
            return cursor.fetchall()

    class Directory(MuftiIdentityProvider):
        provider_id = "synthetic-migration-directory"

        def __init__(self, refs):
            self.refs = frozenset(refs)

        def authenticate(self, credential):
            return None

        def resolve(self, subject_id):
            if subject_id != "synthetic-migration-mufti":
                return None
            return MuftiIdentity(
                subject_id, "MUFTI", True, self.refs, "migration-epoch-1",
                timezone.now() + timedelta(minutes=30),
            )

    try:
        report["tested_sha"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
        if report["tested_sha"] != os.environ["EXPECTED_SHA"]:
            raise RuntimeError("unexpected_tested_revision")
        require_synthetic_write(synthetic_fixtures_only=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::int / 10000")
            report["postgresql_major"] = cursor.fetchone()[0]
        if str(report["postgresql_major"]) != os.environ["PG_EXPECTED_MAJOR"]:
            raise RuntimeError("unexpected_postgres_major")
        if Case.objects.exists():
            raise RuntimeError("migration_check_requires_empty_casework")

        receipts = [services.intake_case(
            original_question="  سؤال اصطناعي لحفظ الأصل\n" + suffix + "  ",
            source_event_id="migration-source-" + suffix,
            requester_id="migration-requester-" + suffix,
            idempotency_key="migration-intake-" + suffix,
            synthetic_fixtures_only=True,
        ) for suffix in ("a", "b")]
        provider = Directory([item["public_ref"] for item in receipts])

        def staff(receipt):
            return dict(case_id=receipt["case_id"], subject_id="synthetic-migration-mufti",
                        provider=provider, synthetic_fixtures_only=True)

        def answer(receipt):
            draft = services.save_answer(
                **staff(receipt), text="جواب بشري اصطناعي لفحص الترحيل.",
                expected_revision=receipt["revision"],
                expected_evidence_version=receipt["evidence_version"],
            )
            return services.record_decision(
                **staff(receipt), answer_id=draft["answers"][-1]["id"], action="APPROVE",
                expected_revision=draft["revision"],
                expected_evidence_version=draft["evidence_version"],
            )

        approved = [answer(receipt) for receipt in receipts]
        services.add_followup(
            token=receipts[1]["token"], text="تفصيل اصطناعي جديد محفوظ بالإصدار التالي.",
            expected_revision=approved[1]["revision"], synthetic_fixtures_only=True,
        )
        answer(services.read_case(**staff(receipts[1])))
        before, counts = snapshot()
        before_guards = guards()
        if not before_guards:
            raise RuntimeError("integrity_guards_missing_before_migration")
        report.update(rows_by_model=counts, rows_sha256=sha256(before.encode()).hexdigest(),
                      guard_count=len(before_guards))

        call_command("migrate", "casework", "0001", interactive=False, verbosity=1)
        if guards() or snapshot()[0] != before:
            raise RuntimeError("reverse_migration_changed_rows_or_kept_guards")
        report["reverse_preserved_rows"] = True
        call_command("migrate", "casework", "0002", interactive=False, verbosity=1)
        if guards() != before_guards or snapshot()[0] != before:
            raise RuntimeError("reapply_changed_rows_or_guards")
        report["reapply_preserved_rows"] = True

        denied = 0
        for receipt in receipts:
            try:
                with transaction.atomic():
                    CaseSource.objects.filter(case_id=receipt["case_id"]).update(
                        original_question="محاولة تغيير أصل الاختبار",
                    )
            except IntegrityError as exc:
                if getattr(exc.__cause__, "sqlstate", None) != "23514":
                    raise
                denied += 1
            else:
                raise RuntimeError("original_update_was_not_rejected")
            status = services.requester_status(receipt["token"], synthetic_fixtures_only=True)
            if status["status"] != "ANSWERED" or status["delivery_verified"]:
                raise RuntimeError("case_state_changed_after_reapply")
        if snapshot()[0] != before:
            raise RuntimeError("rejected_updates_changed_rows")
        report.update(original_updates_denied=denied, cases_verified=len(receipts), status="PASS")
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("V6_POPULATED_MIGRATION_RESULT=" + json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
