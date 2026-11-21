"""Nonempty synthetic recovery inventory and a fresh-process public-reader check.

The stored pins are identifiers, hashes and the original expiry, never an
identity, credential or authority object. A restored database alone cannot
release these records: the verifier constructs explicit isolated fixture
policies and then proves denial without them.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from django.test import Client, override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import AnswerRevision, Case
from apps.experimental_publication import services as publication
from apps.experimental_publication.models import PublicationEdition
from apps.experimental_publication.tests import Authority, Directory
from apps.library_preview.policy import PreviewPolicy, PublicationGrant

from . import services
from .models import PublicAction, PublicRevision, PublicSeries
from .tests import FEATURES, FixtureAuthority

MODELS = (PublicSeries, PublicRevision, PublicAction)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = (
    "public_knowledge_series_guard()",
    "public_knowledge_revision_guard()",
    "public_knowledge_action_guard()",
)
TRIGGERS = tuple(name.removesuffix("()") for name in FUNCTIONS)


@contextmanager
def fixture(ref, *, grants=(), valid_until=None, provider_id="synthetic-publication-directory"):
    directory = Directory([ref])
    directory.provider_id = provider_id
    flags = {
        **FEATURES,
        "FATWA_SCHOLARLY_LINKS_ENABLED": False,
        "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
        "FATWA_PUBLIC_KNOWLEDGE_AUTHORITY": FixtureAuthority(ref, provider_id=provider_id),
        "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": Authority(ref),
        "FATWA_LIBRARY_PREVIEW_POLICY": PreviewPolicy(
            tuple(grants), (), valid_until or timezone.now() + timedelta(minutes=55), True
        ),
    }
    with override_settings(**flags):
        yield directory


def _common(receipt, directory):
    return dict(
        case_id=receipt["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )


def _pins(receipt):
    row = Case.objects.get(pk=receipt["case_id"])
    return {"expected_revision": row.revision, "expected_evidence_version": row.evidence_version}


def _approve_release(common, receipt, row):
    for action, subject in (
        ("REVIEW", "other"),
        ("APPROVE", "publisher"),
        ("RELEASE", "publisher"),
    ):
        row = services.act(
            **{**common, "subject_id": subject},
            **_pins(receipt),
            revision_id=row["id"],
            expected_actions=row["action_count"],
            action=action,
            request_key=str(uuid.uuid4()),
            note="مراجعة استعادة اصطناعية مستقلة",
            minutes=60 if action == "RELEASE" else 0,
            confirmed=True,
        )
    return row


def populate():
    seed_key = uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="PRIVATE public-knowledge recovery question",
        requester_id="public-knowledge-recovery-requester-" + seed_key,
        source_event_id="public-knowledge-recovery-event-" + seed_key,
        idempotency_key="public-knowledge-recovery-intake-" + seed_key,
        synthetic_fixtures_only=True,
    )
    valid_until = timezone.now() + timedelta(minutes=55)
    with fixture(
        receipt["public_ref"],
        valid_until=valid_until,
        provider_id="synthetic-public-knowledge-recovery-" + seed_key,
    ) as directory:
        common = _common(receipt, directory)
        saved = cases.save_answer(
            **common, **_pins(receipt), text="PRIVATE immutable Arabic source for recovery"
        )
        cases.record_decision(
            **common, **_pins(receipt), answer_id=saved["answers"][-1]["id"], action="APPROVE"
        )
        created = publication.create_edition(
            **common,
            **_pins(receipt),
            title="نسخة نشر استعادة اصطناعية",
            category="استعادة اصطناعية",
            body="النص العربي العام المراجع محفوظ كما هو.",
        )
        publication.act(**common, edition_id=created["id"], action="REVIEW", reviewed=True)
        publication.act(
            **{**common, "subject_id": "publisher"}, edition_id=created["id"], action="APPROVE"
        )
        edition = PublicationEdition.objects.get(pk=created["id"])
        grant = PublicationGrant(str(edition.pk), edition.content_sha256)
        policy = PreviewPolicy((grant,), (), valid_until, True)
        with override_settings(FATWA_LIBRARY_PREVIEW_POLICY=policy):
            scholar = services.save(
                **common,
                **_pins(receipt),
                publication_id=str(edition.pk),
                kind="SCHOLAR",
                expected_version=0,
                payload={"name": "عالم استعادة اصطناعي", "bio": ""},
                request_key=str(uuid.uuid4()),
            )
            scholar = _approve_release(common, receipt, scholar)
            translation = services.save(
                **common,
                **_pins(receipt),
                publication_id=str(edition.pk),
                kind="PRESENTATION",
                language="en",
                expected_version=0,
                payload={
                    "title": "Synthetic recovery translation",
                    "question": "",
                    "body": "Human reviewed recovery translation.",
                    "description": "",
                    "scholar_id": scholar["id"],
                    "topic_ids": [],
                    "relation_ids": [],
                },
                request_key=str(uuid.uuid4()),
            )
            translation = _approve_release(common, receipt, translation)
        answer = AnswerRevision.objects.get(pk=edition.answer_id)
        return {
            "case_id": receipt["case_id"],
            "public_ref": receipt["public_ref"],
            "provider_id": directory.provider_id,
            "publication_id": str(edition.pk),
            "publication_sha256": edition.content_sha256,
            "answer_id": str(answer.pk),
            "answer_sha256": answer.text_sha256,
            "valid_until": valid_until.isoformat(),
            "scholar_id": scholar["series_id"],
            "translation_id": translation["id"],
            "translation_sha256": translation["sha256"],
            "tables": {
                model._meta.db_table: [
                    str(identifier)
                    for identifier in (
                        model.objects.filter(
                            **{
                                "case_id"
                                if model is PublicSeries
                                else "series__case_id"
                                if model is PublicRevision
                                else "revision__series__case_id": receipt["case_id"]
                            }
                        )
                        .order_by("id")
                        .values_list("id", flat=True)
                        .iterator()
                    )
                ]
                for model in MODELS
            },
        }


def verify_restored(pins):
    deadline = datetime.fromisoformat(pins["valid_until"])
    if deadline <= timezone.now():
        raise AssertionError("Recovery verification exceeded the original explicit release window")
    grant = PublicationGrant(pins["publication_id"], pins["publication_sha256"])
    with fixture(
        pins["public_ref"],
        grants=(grant,),
        valid_until=deadline,
        provider_id=pins["provider_id"],
    ):
        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        scholar_url = f"/library-preview/knowledge/scholars/{pins['scholar_id']}/"
        translation_url = f"/library-preview/knowledge/publications/{pins['publication_id']}/en/"
        scholar, translated = client.get(scholar_url), client.get(translation_url)
        if (
            scholar.status_code != 200
            or translated.status_code != 200
            or b"Human reviewed recovery translation." not in translated.content
        ):
            raise AssertionError("Exact restored released content is unavailable")
        if "عالم استعادة اصطناعي" not in scholar.content.decode():
            raise AssertionError("Restored public profile differs")
        for response in (scholar, translated):
            if (
                "PRIVATE" in response.content.decode()
                or pins["public_ref"] in response.content.decode()
            ):
                raise AssertionError("Restored private source leaked")
        revision = PublicRevision.objects.get(pk=pins["translation_id"])
        services._verify(revision)
        if (
            revision.sha256 != pins["translation_sha256"]
            or AnswerRevision.objects.get(pk=pins["answer_id"]).text_sha256 != pins["answer_sha256"]
        ):
            raise AssertionError("Restored exact language/source seal differs")
        for model in MODELS:
            identifiers = pins["tables"][model._meta.db_table]
            if not identifiers or model.objects.filter(pk__in=identifiers).count() != len(
                identifiers
            ):
                raise AssertionError("Restored public record inventory differs")
        with override_settings(FATWA_PUBLIC_KNOWLEDGE_AUTHORITY=None):
            if client.get(translation_url).status_code != 404:
                raise AssertionError("Database restore invented release authority")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            if client.get(scholar_url).status_code != 404:
                raise AssertionError("Database restore invented a current identity")
        return {
            "tables": 3,
            "nonempty_tables": 3,
            "reviewed_released_translation": True,
            "reviewed_released_profile": True,
            "original_source_preserved": True,
            "missing_authority_denied": True,
            "missing_identity_denied": True,
        }
