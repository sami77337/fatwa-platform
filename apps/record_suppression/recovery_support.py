"""A restored SQL ledger cannot replace the separately retained current metadata floor."""

import json
import shutil
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.db import DatabaseError, transaction
from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case, CaseEvent, CaseEvidence, CaseSource
from apps.data_privacy import integration as privacy
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.operational_workspace.test_support import Directory

from . import catalog, services, store
from .journal import LocalJournal
from .models import SuppressionEvent
from .test_support import FEATURES, Authority, Fixture

TABLES = (SuppressionEvent._meta.db_table,)
FUNCTIONS = ("rs_event_guard()",)
TRIGGERS = ("rs_event_immutable",)
DENIALS = (
    "feature_disabled",
    "journal_absent",
    "floor_stale",
    "floor_missing",
    "directory_absent",
    "management_mandate_revoked",
    "restored_deleted_answer",
    "late_projection_change",
    "newer_floor_blocks_old_sql",
    "reapplied_current_deletion",
)


def fingerprint(values):
    return catalog.text_hash(json.dumps(list(values), sort_keys=True, default=str))


def rows(pins):
    rows = SuppressionEvent.objects.filter(ledger_id=pins["ledger_id"]).order_by("sequence")
    if rows.count() != 3:
        raise AssertionError("Three suppression decisions must survive recovery")
    return {TABLES[0]: fingerprint(rows.values())}


def originals(pins):
    identifier = pins["case"]["case_id"]
    return {
        model._meta.db_table: fingerprint(
            model.objects.filter(**{field: identifier}).order_by("pk").values()
        )
        for model, field in (
            (Case, "pk"),
            (CaseSource, "case_id"),
            (CaseEvidence, "case_id"),
            (CaseEvent, "case_id"),
            (AnswerRevision, "case_id"),
        )
    }


def populate():
    class RecoveryFixture(Fixture, unittest.TestCase):
        pass

    fixture = RecoveryFixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            fixture.change()
            fixture.change("RESTORE")
            fixture.change(kind="ANSWER", identifier=fixture.answer_id)
            # This path is deliberately outside the DB/private-file backup. A
            # verifier must receive it independently and cannot recreate it
            # from restored SQL rows when it is absent.
            root = (
                Path(".local/qa/functional-continuation/record-suppression-floor")
                / fixture.journal.ledger_id
            )
            root.mkdir(parents=True, mode=0o700, exist_ok=False)
            root = root.resolve()
            for name in ("decisions.json", "lock"):
                shutil.copyfile(fixture.journal.root / name, root / name)
                (root / name).chmod(0o600)
            pins = {
                "ledger_id": fixture.journal.ledger_id,
                "journal_root": str(root),
                "provider_id": fixture.directory.provider_id,
                "case": {name: fixture.receipt[name] for name in ("case_id", "public_ref")},
                "answer_id": fixture.answer_id,
            }
            pins["expected"] = fingerprint([fixture.read()])
            pins["tables"], pins["originals"] = rows(pins), originals(pins)
            pins["floor"] = catalog.digest(fixture.journal.snapshot())
            return pins
        finally:
            fixture.doCleanups()


@contextmanager
def current_floor(pins):
    """Wrap aggregate restored readers without supplying identity or any grants.

    Populate this component last. Keep this context around all subsequent source
    readers, including the other components' restored verifiers. The external
    checkpoint is required independently; it is never inferred from restored SQL.
    """
    journal = LocalJournal(root=pins["journal_root"], ledger_id=pins["ledger_id"])
    current = journal.snapshot()
    if catalog.digest(current) != pins["floor"]:
        raise catalog.SuppressionDenied("suppression_restore_floor_changed")
    with override_settings(
        FATWA_RECORD_SUPPRESSION_ENABLED=True, FATWA_RECORD_SUPPRESSION_JOURNAL=journal
    ):
        expected = store.configuration()
        yield journal
        if store.configuration() != expected or journal.snapshot() != current:
            raise catalog.SuppressionDenied("suppression_restore_floor_changed")


@contextmanager
def fresh_trust(pins):
    directory = Directory([pins["case"]["public_ref"]])
    directory.provider_id = pins["provider_id"]
    authority = Authority(
        directory, [("CASE", pins["case"]["case_id"]), ("ANSWER", pins["answer_id"])]
    )
    with (
        override_settings(
            **{
                **FEATURES,
                "FATWA_RECORD_SUPPRESSION_AUTHORITY": authority,
                "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            }
        ),
        current_floor(pins) as journal,
    ):
        yield directory, authority, journal


def verify_restored(pins):
    def unchanged():
        if rows(pins) != pins["tables"] or originals(pins) != pins["originals"]:
            raise AssertionError("Recovered suppression or source history changed")

    unchanged()
    denials = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (directory, authority, journal):
        base = dict(provider=directory, subject_id="admin", synthetic_fixtures_only=True)

        def read():
            return cases.read_case(
                case_id=pins["case"]["case_id"], **{**base, "subject_id": "mufti"}
            )

        def positive():
            if fingerprint([read()]) != pins["expected"]:
                raise AssertionError("Current restored case projection differs")

        def deny(name, call):
            try:
                call()
            except cases.CaseConflict:
                denials[name] += 1
            else:
                raise AssertionError("Suppression denial was bypassed: " + name)

        def audit():
            with services.inspect(kind="CASE", identifier=pins["case"]["case_id"], **base):
                pass

        positive()
        for name, setting, value in (
            ("feature_disabled", "FATWA_RECORD_SUPPRESSION_ENABLED", False),
            ("journal_absent", "FATWA_RECORD_SUPPRESSION_JOURNAL", None),
            ("directory_absent", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{setting: value}):
                deny(name, audit if name == "directory_absent" else read)
        grant = set(authority.grants)
        authority.revoke("ENTER")
        deny("management_mandate_revoked", audit)
        authority.grants = grant
        deny(
            "restored_deleted_answer",
            lambda: privacy.staff(
                "ANSWER", pins["answer_id"], provider=directory, actor=directory.resolve("mufti")
            ),
        )
        # The denial cases use an isolated copy of the independently read floor.
        # Neither the current external source nor the restored SQL is rewritten.
        with tempfile.TemporaryDirectory(prefix="suppression-recovery-denials-") as temporary:
            scratch = LocalJournal(root=temporary, ledger_id=journal.ledger_id)
            scratch.initialize()
            with override_settings(FATWA_RECORD_SUPPRESSION_JOURNAL=scratch):
                deny("floor_stale", read)
                filename = scratch.root / "decisions.json"
                filename.unlink()
                deny("floor_missing", read)

            def late():
                with privacy.projection():
                    read()
                    with override_settings(FATWA_RECORD_SUPPRESSION_JOURNAL=scratch):
                        # Final guard must run while the invalid floor is current.
                        from apps.data_privacy.services import SCOPES

                        SCOPES.get()[-1].final_pins()

            deny("late_projection_change", late)
        with tempfile.TemporaryDirectory(prefix="suppression-newer-floor-") as temporary:
            newer = LocalJournal(root=temporary, ledger_id=journal.ledger_id)
            newer.initialize()
            expected = []
            for value in journal.snapshot():
                expected = newer.append(expected, value)

            def proposed(action):
                if action == "RECONCILE":
                    return dict(
                        action=action,
                        kind="",
                        identifier="",
                        source_digest="",
                        head="",
                        watermark=store.snapshot(allow_pending=True).watermark,
                        reason="إعادة تطبيق قرار أحدث من قاعدة الاستعادة",
                        request_key=str(uuid.uuid4()),
                    )
                with services.inspect(
                    kind="CASE", identifier=pins["case"]["case_id"], **base
                ) as view:
                    resource = view["item"]
                    return dict(
                        action=action,
                        kind="CASE",
                        identifier=resource["id"],
                        source_digest=resource["source_digest"],
                        head=resource["head"],
                        watermark=view["watermark"],
                        reason="قرار استعادة اصطناعي صريح",
                        request_key=str(uuid.uuid4()),
                    )

            def change(action):
                with services.preview(proposal=proposed(action), **base) as plan:
                    pass
                with services.apply(plan=plan, confirmed=True, **base) as result:
                    return result

            with (
                override_settings(FATWA_RECORD_SUPPRESSION_JOURNAL=newer),
                synthetic_queue_atomic(),
                transaction.atomic(),
            ):

                class OlderSQL(Exception):
                    pass

                try:
                    with transaction.atomic():
                        change("SOFT_DELETE")
                        raise OlderSQL
                except OlderSQL:
                    pass
                if (
                    SuppressionEvent.objects.filter(ledger_id=pins["ledger_id"]).count() != 3
                    or len(newer.snapshot()) != 4
                ):
                    raise AssertionError(
                        "The newer independent floor was not retained across SQL rollback"
                    )
                deny("newer_floor_blocks_old_sql", read)
                change("RECONCILE")
                if not SuppressionEvent.objects.get(sequence=4).recovered:
                    raise AssertionError("Current decisions were not reapplied with an audit")
                deny("reapplied_current_deletion", read)
                change("RESTORE")
                positive()
                transaction.set_rollback(True)
        with synthetic_queue_atomic():
            try:
                with transaction.atomic():
                    SuppressionEvent.objects.filter(ledger_id=pins["ledger_id"]).update(
                        reason="طمس"
                    )
            except DatabaseError:
                immutable = True
            else:
                raise AssertionError("Restored SQL lost immutable history guards")
        positive()  # After every named denial, through the actual current reader.
    unchanged()
    return {
        "status": "PASS",
        "nonempty_tables": 1,
        "audit_revisions": 3,
        "denial_checks": denials,
        "denied_read_count": sum(denials.values()),
        "positive_reads_after_denial": True,
        "immutable_audit": immutable,
        "preserved_originals": True,
        "independent_current_floor_required": True,
        "newer_floor_reapplied_before_availability": True,
        "no_purge_or_anonymization": True,
    }
