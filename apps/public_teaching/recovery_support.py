"""Nonempty teaching history and fresh read-only verification of exact sources."""

import json
import unittest
import uuid
from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as media
from apps.answer_media.models import AnswerPart
from apps.experimental_publication.tests import Authority as PublicationAuthority
from apps.experimental_publication.tests import Directory
from apps.knowledge_links.tests import Authority as KnowledgeAuthority
from apps.library_preview import services as preview
from apps.library_preview.policy import PreviewPolicy, PublicationGrant, ReferenceGrant
from apps.public_knowledge.models import PublicAction, PublicRevision
from apps.public_knowledge.test_scholarly import LinkAuthority
from apps.public_knowledge.tests import FixtureAuthority as KnowledgeCurationAuthority
from apps.research_library import public as library_public
from apps.research_library.recovery_support import _canonical, _digest, _row_pins
from apps.research_library.test_support import FixtureAuthority as LibraryAuthority
from apps.research_library.test_support import bind_identity_snapshot

from . import services
from .models import TeachingAction, TeachingItem, TeachingVersion
from .test_support import FEATURES, FixtureAuthority, TeachingFixture

MODELS = (TeachingItem, TeachingVersion, TeachingAction)
TABLES = tuple(model._meta.db_table for model in MODELS)
FUNCTIONS = ("pt_source_pin(text,uuid)", "pt_item_guard()", "pt_history_guard()")
TRIGGERS = ("pt_item_guard", "pt_version_guard", "pt_action_guard")


class _Seed(TeachingFixture, unittest.TestCase):
    pass


def _owned(case_id):
    filters = ("case_id", "item__case_id", "version__item__case_id")
    return {
        model._meta.db_table: [
            [str(row["id"]), _digest(row)]
            for row in model.objects.filter(**{field: case_id}).order_by("pk").values()
        ]
        for model, field in zip(MODELS, filters, strict=True)
    }


def _source_rows(case_ids):
    return {
        "canonical": [_canonical(identifier) for identifier in case_ids],
        "metadata": _digest(
            [
                list(
                    PublicRevision.objects.filter(series__case_id__in=case_ids)
                    .order_by("pk")
                    .values()
                ),
                list(
                    PublicAction.objects.filter(revision__series__case_id__in=case_ids)
                    .order_by("pk")
                    .values()
                ),
            ]
        ),
        "library": _row_pins(case_ids[0]),
    }


def _read(pins):
    with services.public_projection() as current:
        scholar = current.scholar(pins["scholar_id"])
        series = current.read(pins["series_id"], "SERIES")[1]
        lessons = [
            current.lesson(identifier, series_id=pins["series_id"])
            for identifier in pins["lesson_ids"]
        ]
        audio_hashes = [
            sha256(current.audio(identifier, 1)["raw"]).hexdigest()
            for identifier in pins["lesson_ids"]
        ]
        if any(value != pins["audio_sha256"] for value in audio_hashes):
            raise AssertionError("restored teaching original bytes differ")
        if [row["id"] for row in series["members"]] != pins["lesson_ids"]:
            raise AssertionError("restored teaching order or stable IDs differ")
        if (
            not scholar["publications"]
            or len(scholar["lessons"]) != 2
            or len(scholar["materials"]) != 1
        ):
            raise AssertionError("restored scholar content is incomplete")
        if "PRIVATE" in str((scholar, series, lessons)):
            raise AssertionError("restored public teaching leaked private source metadata")
        digest = _digest((scholar, series, lessons))
    with library_public.public_projection() as current:
        raw = current.content(pins["material_id"])["raw"]
        if sha256(raw).hexdigest() != pins["material_sha256"]:
            raise AssertionError("restored attributed material bytes differ")
    return digest


def populate():
    with override_settings(**FEATURES):
        seed = _Seed()
        # Scholar profiles bind to a provider/subject pair across all cases.
        # Each independent recovery seed represents a distinct synthetic actor.
        seed.fixture_provider_id = "synthetic-teaching-recovery-" + uuid.uuid4().hex
        try:
            seed.setUp()
            rows = seed.complete()
            cases = [
                {"case_id": row["case_id"], "public_ref": row["public_ref"]}
                for row in (seed.receipt, seed.second)
            ]
            pins = {
                "cases": cases,
                "provider_id": seed.directory.provider_id,
                "scholar_id": str(rows["scholar"].series_id),
                "series_id": rows["series"]["public_id"],
                "lesson_ids": [row["public_id"] for row in rows["lessons"]],
                "material_id": str(rows["material"].pk),
                "material_sha256": rows["material"].blob.sha256,
                "part_id": str(seed.part.pk),
                "audio_sha256": seed.part.sha256,
                "publications": [asdict(grant) for grant in seed.preview_policy.publications],
                "references": [asdict(grant) for grant in seed.preview_policy.references],
                "valid_until": seed.preview_policy.valid_until.isoformat(),
                "tables": _owned(cases[0]["case_id"]),
                "source_rows": _source_rows([row["case_id"] for row in cases]),
            }
            if any(not rows for rows in pins["tables"].values()):
                raise AssertionError("teaching recovery inventory is empty")
            pins["public_sha256"] = _read(pins)
            return json.loads(json.dumps(pins))
        finally:
            seed.doCleanups()


def _denied(pins, *, scholar=False):
    try:
        with services.public_projection() as current:
            if scholar:
                result = current.scholar(pins["scholar_id"])
                if not result["materials"]:
                    return 1
            else:
                current.audio(pins["lesson_ids"][0], 1)
    except preview.PreviewUnavailable:
        return 1
    raise AssertionError("restored teaching read inherited missing current trust")


def verify_restored(pins):
    case_ids = [row["case_id"] for row in pins["cases"]]
    refs = [row["public_ref"] for row in pins["cases"]]
    if _owned(case_ids[0]) != pins["tables"] or _source_rows(case_ids) != pins["source_rows"]:
        raise AssertionError("restored teaching/source row pins differ")
    deadline = datetime.fromisoformat(pins["valid_until"])
    if deadline <= timezone.now():
        raise AssertionError("teaching recovery exceeded original finite source availability")
    directory = Directory(refs)
    directory.provider_id = pins["provider_id"]
    bind_identity_snapshot(directory)
    authority = FixtureAuthority(refs, provider_id=directory.provider_id)
    rights = LinkAuthority(refs, provider_id=directory.provider_id)
    authority.until = deadline
    denied = {}
    with override_settings(
        **{
            **FEATURES,
            "FATWA_CASEWORK_IDENTITY_PROVIDER": directory,
            "FATWA_PUBLIC_TEACHING_AUTHORITY": authority,
            "FATWA_SCHOLARLY_LINKS_AUTHORITY": rights,
            "FATWA_RESEARCH_LIBRARY_AUTHORITY": LibraryAuthority(
                *refs, provider_id=directory.provider_id
            ),
            "FATWA_PUBLIC_KNOWLEDGE_AUTHORITY": KnowledgeCurationAuthority(
                refs[0], provider_id=directory.provider_id
            ),
            "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY": PublicationAuthority(refs[0]),
            "FATWA_KNOWLEDGE_LINKS_AUTHORITY": KnowledgeAuthority(refs[0]),
            "FATWA_LIBRARY_PREVIEW_POLICY": PreviewPolicy(
                tuple(PublicationGrant(**row) for row in pins["publications"]),
                tuple(ReferenceGrant(**row) for row in pins["references"]),
                deadline,
                True,
            ),
        }
    ):
        if _read(pins) != pins["public_sha256"]:
            raise AssertionError("restored teaching public projection differs")
        for label, setting in (
            ("missing_authority", "FATWA_PUBLIC_TEACHING_AUTHORITY"),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER"),
            ("missing_source_authority", "FATWA_SCHOLARLY_LINKS_AUTHORITY"),
        ):
            with override_settings(**{setting: None}):
                denied[label] = _denied(pins)
        old = directory.identities["publisher"]
        directory.identities["publisher"] = replace(old, active=False)
        denied["revoked_current_release_actor"] = _denied(pins)
        directory.identities["publisher"] = old
        authority.denied.add("PUBLIC_LESSON_CONTENT")
        denied["missing_public_content_right"] = _denied(pins)
        authority.denied.clear()
        authority.denied.add(("READ_SOURCE", "LIBRARY"))
        denied["missing_attributed_material_right"] = _denied(pins, scholar=True)
        authority.denied.clear()
        if _read(pins) != pins["public_sha256"]:
            raise AssertionError("restored positive reads changed after current denial checks")
        if (
            sha256(media.raw_for_part(AnswerPart.objects.get(pk=pins["part_id"]))).hexdigest()
            != pins["audio_sha256"]
        ):
            raise AssertionError("teaching verification changed original recording")
    if _owned(case_ids[0]) != pins["tables"] or _source_rows(case_ids) != pins["source_rows"]:
        raise AssertionError("teaching recovery verification wrote rows")
    return {
        "table_count": 3,
        "item_count": 4,
        "version_count": 4,
        "action_count": 12,
        "exact_original_audio_sha256": pins["audio_sha256"],
        "exact_material_sha256": pins["material_sha256"],
        "stable_series_member_order": True,
        "denied_read_count": sum(denied.values()),
        "denial_checks": denied,
        "positive_reads_after_denial": True,
        "source_and_teaching_rows_unchanged": True,
    }
