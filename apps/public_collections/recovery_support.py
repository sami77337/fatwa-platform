"""Nonempty recovery fixture; pins carry no authority or identity credentials."""

import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import CaseSource
from apps.experimental_publication.tests import Directory
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy
from apps.public_knowledge.tests import FixtureAuthority as KnowledgeAuthority
from apps.research_library import services as library
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority
from apps.research_library.test_support import payload

from . import services
from .models import CollectionAction, CollectionRevision, CollectionSeries
from .test_support import FEATURES, FixtureAuthority, identity_snapshot

MODELS = (CollectionSeries, CollectionRevision, CollectionAction)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("pcol_series_guard()", "pcol_revision_guard()", "pcol_action_guard()")
TRIGGERS = tuple(name.removesuffix("()") for name in FUNCTIONS)


@contextmanager
def fixture(ref, valid_until):
    directory = Directory([ref])
    directory.identities = {
        subject: replace(actor, valid_until=valid_until)
        for subject, actor in directory.identities.items()
    }
    directory.projection_epoch = lambda: identity_snapshot(directory)
    with override_settings(
        **{
            **FEATURES,
            "FATWA_SCHOLARLY_LINKS_ENABLED": False,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLIC_KNOWLEDGE_AUTHORITY": KnowledgeAuthority(ref),
            "FATWA_RESEARCH_LIBRARY_AUTHORITY": LibraryAuthority(ref),
            "FATWA_PUBLIC_COLLECTIONS_AUTHORITY": FixtureAuthority(ref),
            "FATWA_LIBRARY_PREVIEW_POLICY": PreviewPolicy((), (), valid_until, True),
        }
    ):
        yield directory


def populate():
    key = "collections-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="PRIVATE synthetic collection recovery question",
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    deadline = timezone.now() + timedelta(minutes=55)
    with fixture(receipt["public_ref"], deadline) as directory:
        common = dict(
            case_id=receipt["case_id"],
            subject_id="editor",
            provider=directory,
            synthetic_fixtures_only=True,
        )
        pins = dict(expected_revision=1, expected_evidence_version=1)
        material = library.write_material(
            **common,
            **pins,
            namespace="collections-recovery",
            external_id=key,
            payload=payload(title="مصدر استعادة وصفي اصطناعي"),
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        for action in ("REVIEW", "APPROVE", "RELEASE"):
            material = library.decide(
                **{**common, "subject_id": "other" if action == "REVIEW" else "publisher"},
                **pins,
                version_id=material["version_id"],
                action=action,
                note="قرار استعادة اصطناعي مستقل",
                expected_actions=material["action_count"],
                request_key=uuid.uuid4(),
                confirmed=True,
                uses=["PUBLIC_METADATA"] if action == "APPROVE" else [],
                minutes=60 if action == "APPROVE" else 50 if action == "RELEASE" else 0,
            )
        row = services.save(
            **common,
            **pins,
            kind="TOPIC",
            title="موضوع استعادة اصطناعي",
            introduction="مقدمة بشرية محفوظة مع ترتيب الإحالات",
            members=[f"LIBRARY|{material['version_id']}|{material['digest']}"],
            featured=True,
            expected_version=0,
            request_key=uuid.uuid4(),
        )
        for action in ("REVIEW", "APPROVE", "RELEASE"):
            row = services.act(
                **{**common, "subject_id": "other" if action == "REVIEW" else "publisher"},
                **pins,
                revision_id=row["id"],
                action=action,
                expected_actions=row["action_count"],
                request_key=uuid.uuid4(),
                note="مراجعة استعادة مستقلة",
                confirmed=True,
                minutes=60 if action == "RELEASE" else 0,
            )
        return {
            "case_id": receipt["case_id"],
            "public_ref": receipt["public_ref"],
            "source_sha256": CaseSource.objects.get(case_id=receipt["case_id"]).question_sha256,
            "revision_id": row["id"],
            "public_id": row["public_id"],
            "sha256": row["sha256"],
            "library_version_id": material["version_id"],
            "library_digest": material["digest"],
            "valid_until": deadline.isoformat(),
            "tables": {
                model._meta.db_table: [
                    str(pk)
                    for pk in model.objects.filter(
                        **{
                            "case_id"
                            if model is CollectionSeries
                            else "series__case_id"
                            if model is CollectionRevision
                            else "revision__series__case_id": receipt["case_id"]
                        }
                    )
                    .order_by("pk")
                    .values_list("pk", flat=True)
                ]
                for model in MODELS
            },
        }


def verify_restored(pins):
    deadline = datetime.fromisoformat(pins["valid_until"])
    if deadline <= timezone.now():
        raise AssertionError("Collection recovery exceeded its original explicit release window")
    with fixture(pins["public_ref"], deadline):
        record = CollectionRevision.objects.select_related("series").get(pk=pins["revision_id"])
        services.verify(record)
        if (
            record.sha256 != pins["sha256"]
            or record.payload["members"][0]["id"] != pins["library_version_id"]
            or record.payload["members"][0]["sha256"] != pins["library_digest"]
        ):
            raise AssertionError("Restored exact collection/member identity changed")
        if CaseSource.objects.get(case_id=pins["case_id"]).question_sha256 != pins["source_sha256"]:
            raise AssertionError("Restored private original changed")
        with services.public_projection() as rows:
            row = next((row for row in rows if row["id"] == pins["public_id"]), None)
            if (
                row is None
                or row["title"] != "موضوع استعادة اصطناعي"
                or row["members"][0]["title"] != "مصدر استعادة وصفي اصطناعي"
            ):
                raise AssertionError("Restored explicit released projection is unavailable")
            if pins["public_ref"] in str(row) or "PRIVATE" in str(row):
                raise AssertionError("Restored collection leaked private data")
        for model in MODELS:
            identifiers = pins["tables"][model._meta.db_table]
            if not identifiers or model.objects.filter(pk__in=identifiers).count() != len(
                identifiers
            ):
                raise AssertionError("Restored collection record inventory differs")
        with override_settings(FATWA_PUBLIC_COLLECTIONS_AUTHORITY=None):
            try:
                with services.public_projection():
                    raise AssertionError("Restored content acquired authority from storage")
            except preview.PreviewUnavailable:
                pass
    return {"status": "PASS", "tables": pins["tables"], "exact_public_id": pins["public_id"]}
