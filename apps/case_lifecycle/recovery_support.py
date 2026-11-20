"""Real-service synthetic population; fresh-process readers rebuild policy only."""

import uuid
from contextlib import contextmanager
from dataclasses import replace

from django.conf import settings
from django.test import override_settings

from apps.case_assignments.tests import Directory
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent
from apps.delivery_queue.services import synthetic_queue_atomic

from . import services
from .models import LifecycleEvent
from .tests import Authority

TABLES = (LifecycleEvent._meta.db_table,)
FUNCTIONS = ("lifecycle_event_guard()",)
TRIGGERS = ("lifecycle_event_guard",)


@contextmanager
def _fixture(refs):
    directory = Directory(refs)
    authority = Authority(refs, directory.provider_id)
    with override_settings(
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_CASE_LIFECYCLE_ENABLED=True,
        FATWA_CASE_LIFECYCLE_AUTHORITY=authority,
    ):
        yield directory


def _common(receipt, directory):
    return dict(
        case_id=receipt["case_id"],
        subject_id="mufti-a",
        provider=directory,
        synthetic_fixtures_only=True,
    )


def _pins(receipt):
    case = Case.objects.get(pk=receipt["case_id"])
    return dict(expected_revision=case.revision, expected_evidence_version=case.evidence_version)


def _canonical(receipt):
    case = Case.objects.get(pk=receipt["case_id"])
    return services._digest(
        [
            list(Case.objects.filter(pk=case.pk).values()),
            case.source.original_question,
            case.source.question_sha256,
            list(case.evidence.order_by("version").values()),
            list(case.answers.order_by("revision").values()),
            list(case.decisions.order_by("id").values()),
            list(case.events.order_by("sequence").values()),
        ]
    )


def populate():
    receipts = [
        cases.intake_case(
            original_question="سؤال استعادة دورة حياة اصطناعي " + suffix,
            requester_id="lifecycle-recovery-" + suffix,
            source_event_id="lifecycle-recovery-" + suffix,
            idempotency_key="lifecycle-recovery-" + suffix,
            synthetic_fixtures_only=True,
        )
        for suffix in ("closed", "archived", "reopened")
    ]
    with _fixture([row["public_ref"] for row in receipts]) as directory:
        for index, receipt in enumerate(receipts):
            common = _common(receipt, directory)
            draft = cases.save_answer(**common, **_pins(receipt), text="جواب بشري اصطناعي محفوظ")
            cases.record_decision(
                **common, **_pins(receipt), answer_id=draft["answers"][-1]["id"], action="APPROVE"
            )
            operations = ("CLOSE",) if index == 0 else ("CLOSE", "ARCHIVE")
            for version, action in enumerate(operations):
                services.command(
                    **common,
                    **_pins(receipt),
                    action=action,
                    reason="إجراء استعادة اصطناعي " + action,
                    expected_version=version,
                    command_id=uuid.uuid4(),
                    without_delivery=action == "CLOSE",
                )
            if index == 2:
                with synthetic_queue_atomic():
                    case = Case.objects.get(pk=receipt["case_id"])
                    cases.add_followup(
                        token=receipt["token"],
                        text="وقائع استعادة جديدة",
                        expected_revision=case.revision,
                        synthetic_fixtures_only=True,
                    )
                    case.refresh_from_db()
                    services.record_followup(case=case, event=case.events.latest("sequence"))
        tables = {
            TABLES[0]: [[str(row.pk), row.sha256] for row in LifecycleEvent.objects.order_by("id")]
        }
        if not tables[TABLES[0]]:
            raise AssertionError("lifecycle recovery table must be nonempty")
        return {
            "cases": [
                {
                    "case_id": row["case_id"],
                    "public_ref": row["public_ref"],
                    "canonical_sha256": _canonical(row),
                    "state": services.desk(**_common(row, directory))["state"],
                }
                for row in receipts
            ],
            "tables": tables,
        }


def _verify_available(pins, directory):
    receipts = pins["cases"]
    for receipt in receipts:
        result = services.desk(**_common(receipt, directory))
        if (
            result["state"] != receipt["state"]
            or _canonical(receipt) != receipt["canonical_sha256"]
        ):
            raise AssertionError("restored lifecycle/canonical pins changed")
    actual = [[str(row.pk), row.sha256] for row in LifecycleEvent.objects.order_by("id")]
    if not actual or actual != pins["tables"][TABLES[0]]:
        raise AssertionError("restored lifecycle history changed")
    common = {"subject_id": "mufti-a", "provider": directory, "synthetic_fixtures_only": True}
    visible = services.inbox(**common, state="ALL")
    if visible["counts"] != {"OPEN": 1, "CLOSED": 1, "ARCHIVED": 1}:
        raise AssertionError("restored lifecycle visibility differs")
    rows = cases.list_cases(**common)
    with services.queue_projection(rows, **common) as normal:
        if len(normal) != 1 or normal[0]["public_ref"] != receipts[2]["public_ref"]:
            raise AssertionError("restored normal queue lifecycle differs")
    return actual, rows


def _deny_reads(receipt, rows, reason):
    # Native requests resolve their current provider from configuration. Cached
    # case DTOs and durable approval history must not substitute for that trust.
    common = {
        "subject_id": "mufti-a",
        "provider": getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        "synthetic_fixtures_only": True,
    }

    def queue():
        with services.queue_projection(rows, **common):
            pass

    count = 0
    for reader in (
        lambda: services.desk(**common, case_id=receipt["case_id"]),
        lambda: services.inbox(**common, state="ALL"),
        queue,
    ):
        try:
            reader()
        except cases.CaseConflict as exc:
            if str(exc) != reason:
                raise
            count += 1
        else:
            raise AssertionError("restored lifecycle read survived missing or revoked trust")
    return count


def verify_restored(pins):
    receipts = pins["cases"]
    before = list(CaseEvent.objects.values()), list(LifecycleEvent.objects.values())
    with _fixture([row["public_ref"] for row in receipts]) as directory:
        actual, rows = _verify_available(pins, directory)
        archived = receipts[1]
        denied = {}
        with override_settings(FATWA_CASE_LIFECYCLE_AUTHORITY=None):
            denied["missing_authority"] = _deny_reads(
                archived, rows, "lifecycle_authority_required"
            )
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            denied["missing_identity_provider"] = _deny_reads(
                archived, rows, "lifecycle_identity_unavailable"
            )
        actor = directory.identities["mufti-a"]
        try:
            directory.identities["mufti-a"] = replace(actor, active=False)
            denied["revoked_current_reader"] = _deny_reads(
                archived, rows, "lifecycle_identity_unavailable"
            )
        finally:
            directory.identities["mufti-a"] = actor
        _verify_available(pins, directory)
    if before != (list(CaseEvent.objects.values()), list(LifecycleEvent.objects.values())):
        raise AssertionError("restored lifecycle readers wrote records")
    return {
        "table_count": 1,
        "case_count": 3,
        "event_count": len(actual),
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
    }
