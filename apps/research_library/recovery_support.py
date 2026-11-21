"""Nonempty real-service fixtures and exact restored readers, without saved grants."""

import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy

from . import public, services
from .models import LibraryBlob, LibraryDecision, LibraryItem, LibraryVersion
from .test_support import FEATURES, FixtureAuthority, bind_identity_snapshot, payload, video

TABLES = tuple(
    model._meta.db_table for model in (LibraryBlob, LibraryItem, LibraryVersion, LibraryDecision)
)
FUNCTIONS = ("rl_blob_guard()", "rl_item_guard()", "rl_item_complete()", "rl_history_guard()")
TRIGGERS = (
    "rl_blob_guard",
    "rl_item_guard",
    "rl_item_complete",
    "rl_version_guard",
    "rl_decision_guard",
)
BOOK_BYTES = "نص كتاب اصطناعي للاستعادة\r\n  تبقى البايتات الأصلية كما هي  \n".encode()


def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


@contextmanager
def _fixture(receipt):
    """Rebuild synthetic trust only; never replace the harness's storage adapter."""
    directory = bind_identity_snapshot(Directory([receipt["public_ref"]]))
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_RESEARCH_LIBRARY_AUTHORITY": FixtureAuthority(receipt["public_ref"]),
            "FATWA_LIBRARY_PREVIEW_POLICY": PreviewPolicy(
                (), (), timezone.now() + timedelta(minutes=30), True
            ),
        }
    ):
        yield dict(
            case_id=receipt["case_id"],
            subject_id="editor",
            provider=directory,
            synthetic_fixtures_only=True,
        )


def _canonical(case_id):
    case = Case.objects.get(pk=case_id)
    return _digest(
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


def _row_pins(case_id):
    versions = LibraryVersion.objects.filter(item__case_id=case_id)
    queries = (
        LibraryBlob.objects.filter(pk__in=versions.values("blob_id")),
        LibraryItem.objects.filter(case_id=case_id),
        versions,
        LibraryDecision.objects.filter(version__item__case_id=case_id),
    )
    result = {}
    for query in queries:
        records = []
        for row in query.order_by("pk").values():
            if "original" in row and row["original"] is not None:
                row["original"] = bytes(row["original"]).hex()
            records.append([str(row[query.model._meta.pk.attname]), _digest(row)])
        if not records:
            raise AssertionError("library recovery tables must be nonempty")
        result[query.model._meta.db_table] = records
    return result


def _write(common, kind, key, raw, filename, media_type, *, number=0, title=""):
    return services.write_material(
        **common,
        namespace="synthetic-library-recovery",
        external_id=key,
        payload=payload(
            kind,
            title=title or "مادة استعادة اصطناعية " + kind,
            edition_label="نسخة استعادة " + str(number + 1),
        ),
        file_bytes=raw,
        filename=filename,
        media_type=media_type,
        expected_version=number,
        expected_revision=1,
        expected_evidence_version=1,
        request_key=uuid.uuid4(),
    )


def _decide(common, record, action, *, uses=None):
    return services.decide(
        **{**common, "subject_id": "other" if action == "REVIEW" else "publisher"},
        version_id=record["version_id"],
        action=action,
        note="مراجعة بشرية اصطناعية مستقلة للنسخة وحقوقها",
        expected_actions=record["action_count"],
        request_key=uuid.uuid4(),
        confirmed=True,
        expected_revision=1,
        expected_evidence_version=1,
        uses=uses or [],
        minutes=30 if action == "APPROVE" else (15 if action == "RELEASE" else 0),
    )


def populate():
    suffix = uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="سؤال مكتبة اصطناعي خاص لا ينشر ضمن المواد",
        requester_id="library-recovery-" + suffix,
        source_event_id="library-recovery-" + suffix,
        idempotency_key="library-recovery-" + suffix,
        synthetic_fixtures_only=True,
    )
    before = _canonical(receipt["case_id"])
    with _fixture(receipt) as common:
        book = _write(common, "BOOK", "book", BOOK_BYTES, "book.txt", "text/plain")
        book = _decide(common, book, "REVIEW")
        book = _decide(
            common, book, "APPROVE", uses=["READ", "DOWNLOAD", "CITE", "EXPORT", "OFFLINE"]
        )
        book_draft = _write(common, "BOOK", "book", b"", "", "", number=1)
        recording = _write(common, "VIDEO", "video", video(), "video.webm", "video/webm")
        recording = _decide(common, recording, "REVIEW")
        recording = _decide(common, recording, "APPROVE", uses=sorted(services.USES))
        recording = _decide(common, recording, "RELEASE")
        video_draft = _write(common, "VIDEO", "video", b"", "", "", number=1)
        if _canonical(receipt["case_id"]) != before:
            raise AssertionError("library fixture changed canonical case facts")
        return {
            "case": {
                "case_id": receipt["case_id"],
                "public_ref": receipt["public_ref"],
                "canonical_sha256": before,
            },
            "versions": {
                label: {
                    key: record[key]
                    for key in ("version_id", "item_id", "public_id", "number", "digest", "file")
                }
                for label, record in (
                    ("book", book),
                    ("book_draft", book_draft),
                    ("video", recording),
                    ("video_draft", video_draft),
                )
            },
            "tables": _row_pins(receipt["case_id"]),
        }


def _verify_available(common, expected):
    for label, record in expected.items():
        actual = services.read_material(**common, version_id=record["version_id"])
        if any(actual[key] != value for key, value in record.items()):
            raise AssertionError("restored library edition changed")
        if label.endswith("_draft"):
            try:
                services.file_content(**common, version_id=record["version_id"])
            except cases.CaseConflict as exc:
                if str(exc) != "library_use_unavailable":
                    raise
            else:
                raise AssertionError("unapproved edition inherited file rights")
        else:
            raw = BOOK_BYTES if label == "book" else video()
            for usage in ("READ", "DOWNLOAD"):
                content = services.file_content(
                    **common, version_id=record["version_id"], usage=usage
                )
                if content["raw"] != raw or content["sha256"] != sha256(raw).hexdigest():
                    raise AssertionError("restored library original bytes changed")
    with public.public_projection() as snapshot:
        if set(snapshot.records) != {expected["video"]["version_id"]}:
            raise AssertionError("restored library public rights changed")
        recording = snapshot.read(expected["video"]["version_id"])
        if (
            recording["number"] != 1
            or snapshot.content(recording["version_id"])["raw"] != video()
            or snapshot.content(recording["version_id"], usage="DOWNLOAD")["raw"] != video()
        ):
            raise AssertionError("restored public recording changed")
    result = services.browse(**common)
    if result["total"] != 2 or {row["number"] for row in result["rows"]} != {2}:
        raise AssertionError("restored current-edition browse changed")


def _deny_private_reads(common, version_id, reason):
    # A native request binds its current provider from configuration. Do not
    # reuse the fixture's former provider after removing that configuration.
    current = {**common, "provider": getattr(settings, "FATWA_CASEWORK_IDENTITY_PROVIDER", None)}
    count = 0
    for reader in (services.read_material, services.file_content):
        try:
            reader(**current, version_id=version_id)
        except cases.CaseConflict as exc:
            if str(exc) != reason:
                raise
            count += 1
        else:
            raise AssertionError("restored library read survived missing or revoked trust")
    return count


def _deny_public_read(version_id):
    try:
        with public.public_projection() as snapshot:
            snapshot.content(version_id)
    except preview.PreviewUnavailable:
        return 1
    raise AssertionError("restored public source inherited a durable access grant")


def verify_restored(pins):
    receipt, expected = pins["case"], pins["versions"]
    before = _row_pins(receipt["case_id"])
    if before != pins["tables"] or _canonical(receipt["case_id"]) != receipt["canonical_sha256"]:
        raise AssertionError("restored library row or canonical pins changed")
    with _fixture(receipt) as common:
        _verify_available(common, expected)
        book_id, video_id = expected["book"]["version_id"], expected["video"]["version_id"]
        denied = {}
        with override_settings(FATWA_RESEARCH_LIBRARY_AUTHORITY=None):
            denied["missing_authority"] = _deny_private_reads(
                common, book_id, "library_authority_required"
            ) + _deny_public_read(video_id)
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            denied["missing_identity_provider"] = _deny_private_reads(
                common, book_id, "case_access_denied"
            ) + _deny_public_read(video_id)
        directory = common["provider"]
        reader = directory.identities["editor"]
        try:
            directory.identities["editor"] = replace(reader, active=False)
            denied["revoked_current_reader"] = _deny_private_reads(
                common, book_id, "case_access_denied"
            )
        finally:
            directory.identities["editor"] = reader
        publisher = directory.identities["publisher"]
        try:
            directory.identities["publisher"] = replace(publisher, active=False)
            denied["revoked_public_release_actor"] = _deny_public_read(video_id)
        finally:
            directory.identities["publisher"] = publisher
        # Re-open exact originals after restoring only current synthetic trust.
        _verify_available(common, expected)
    if (
        _row_pins(receipt["case_id"]) != before
        or _canonical(receipt["case_id"]) != receipt["canonical_sha256"]
    ):
        raise AssertionError("restored library verification wrote records")
    return {
        "table_count": len(TABLES),
        "case_count": 1,
        "blob_count": 2,
        "item_count": 2,
        "version_count": 4,
        "decision_count": 5,
        "public_version_count": 1,
        "draft_denied_count": 2,
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
    }
