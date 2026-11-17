"""A fresh process verifies restored V9 services, permissions, bytes and SQL guards."""

import argparse
import json
import os
import sys

import django


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-bundle")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--scratch")
    parser.add_argument("--pg-bin")
    args = parser.parse_args()
    django.setup()
    if args.restore_bundle:
        from .service import restore

        restored = restore(
            bundle=args.restore_bundle,
            expected_manifest_sha256=args.manifest_sha256,
            scratch=args.scratch,
            pg_bin=args.pg_bin,
            synthetic_fixtures_only=True,
            offline=True,
        )
        # Exec guarantees a brand new Django connection/profile after restoration.
        os.environ.update(
            PGDATABASE=restored["database"],
            PGTESTDATABASE="test_" + restored["database"],
            RECOVERY_PRIVATE_ROOT=restored["private_root"],
        )
        os.execv(sys.executable, [sys.executable, "-m", "apps.platform_recovery.verify_fixture"])
    from django.core.management import call_command
    from django.db import IntegrityError, connection, transaction
    from django.test import override_settings

    from apps.answer_media import services as answers
    from apps.answer_media.models import AnswerPart
    from apps.answer_media.tests import audio_fixture
    from apps.case_attachments import services as attachments
    from apps.case_attachments.models import CaseAttachment
    from apps.case_attachments.tests import staff_common
    from apps.casework import services as cases
    from apps.casework.models import AnswerRevision, Case
    from apps.intake_workflow.guards import require_owned_database
    from apps.private_media.filesystem import FileSystemStorage
    from tests.casework.test_core import TestDirectory

    fixture = json.load(sys.stdin)
    require_owned_database(synthetic_fixtures_only=True)
    storage = FileSystemStorage(os.environ["RECOVERY_PRIVATE_ROOT"], synthetic_fixtures_only=True)
    with override_settings(
        FATWA_PRIVATE_MEDIA_STORAGE=storage,
        FATWA_CASE_ATTACHMENTS_ENABLED=True,
        FATWA_ANSWER_MEDIA_ENABLED=True,
        FATWA_ANSWER_MEDIA_PRIVATE_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=TestDirectory([fixture["receipt"]["public_ref"]]),
    ):
        receipt = fixture["receipt"]
        common = staff_common(receipt)
        case = cases.read_case(**common)
        assert case["evidence_version"] == 2
        assert AnswerRevision.objects.filter(case_id=receipt["case_id"]).count() == 2
        assert len(case["answers"]) == 2
        expected = bytes.fromhex(fixture["attachment_hex"])
        assert (
            attachments.requester_read(
                token=receipt["token"],
                attachment_id=fixture["attachment"]["id"],
                synthetic_fixtures_only=True,
            )["raw"]
            == expected
        )
        # The backup never fabricates an external identity authority.
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            try:
                answers.requester_snapshot(token=receipt["token"], synthetic_fixtures_only=True)
                raise AssertionError("missing restored identity authority must fail closed")
            except cases.CaseConflict:
                pass
        private = answers.requester_snapshot(token=receipt["token"], synthetic_fixtures_only=True)
        assert private["package"]["approved"]
        assert private["package"]["answer_id"] == case["approved_answer_id"]
        for part in private["package"]["parts"]:
            if part["kind"] == "AUDIO":
                assert (
                    answers.requester_read(
                        token=receipt["token"], part_id=part["id"], synthetic_fixtures_only=True
                    )["raw"]
                    == audio_fixture()["raw"]
                )
        for part in AnswerPart.objects.exclude(kind="TEXT"):
            assert answers.raw_for_part(part) == audio_fixture()["raw"]
        for bad in (
            lambda: attachments.requester_read(
                token=fixture["other"]["token"],
                attachment_id=fixture["attachment"]["id"],
                synthetic_fixtures_only=True,
            ),
            lambda: cases.read_case(
                **staff_common(
                    receipt, TestDirectory([receipt["public_ref"]], role="ORGANIZER_ADMIN")
                )
            ),
            lambda: cases.read_case(
                **staff_common(receipt, TestDirectory([fixture["other"]["public_ref"]]))
            ),
        ):
            try:
                bad()
                raise AssertionError("restored access must remain denied")
            except cases.CaseConflict:
                pass
        try:
            with transaction.atomic():
                CaseAttachment.objects.filter(pk=fixture["attachment"]["id"]).update(
                    case_id=fixture["other"]["case_id"]
                )
            raise AssertionError("cross-case binding must remain immutable")
        except IntegrityError:
            pass
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("UPDATE wave7_synthetic_ownership SET database_oid=0")
            raise AssertionError("restored ownership marker must be immutable")
        except IntegrityError:
            pass
        current = Case.objects.get(pk=receipt["case_id"])
        # Source token still resolves; no identity scopes or approvals are invented by restore.
        cases.add_followup(
            token=receipt["token"],
            text="وقائع اصطناعية جديدة بعد الاستعادة",
            expected_revision=current.revision,
            synthetic_fixtures_only=True,
        )
        try:
            answers.requester_snapshot(token=receipt["token"], synthetic_fixtures_only=True)
            raise AssertionError("new facts must close old answer")
        except cases.CaseConflict:
            pass
        call_command("check", verbosity=0)
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)
    print("RESTORED_SERVICE_CHECKS_PASS")


if __name__ == "__main__":
    main()
