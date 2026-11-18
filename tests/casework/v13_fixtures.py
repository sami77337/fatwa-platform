"""V13 synthetic input/authorities and canonical inventory; never seeded decisions."""

import json
import math
import struct
import wave
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from django.db import connection
from django.utils import timezone

from apps.classification_review.authority import ClassificationAuthority
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from apps.timed_citations.rights import TimedMediaRights
from tests.casework.v11_fixtures import Directory
from tests.casework.v12_fixtures import APPROVED_TEXT as APPROVED_TEXT
from tests.casework.v12_fixtures import inventory as previous_inventory

OUT = Path(".local/qa/v13/browser")
QUESTION = "سؤال صوتي اصطناعي لرحلة V13؛ لا صوت شخص حقيقي ولا حكم شرعي."
CLASSIFICATION_LABEL = "تصنيف V13 خاص للمراجعة"
CLASSIFICATION_REASON = "اقتراح اصطناعي من بيانات الفهرس، لا علاقة علمية من التشابه."
TIMED_REASON = "موضع بشري اصطناعي في أصل التسجيل، دون تفريغ أو اقتباس مولد."


def write_fake_microphone(path):
    """Only generated tones enter Chrome's fake audio device; never a real mic."""
    with wave.open(str(path), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(48000)
        sound.writeframes(
            b"".join(
                struct.pack("<h", int(10000 * math.sin(i * 2 * math.pi * 440 / 48000)))
                for i in range(96000)
            )
        )


def bootstrap_catalog():
    """Catalog and fixture identities only: the browser must create the one case."""
    from apps.reference.ingest import ingest_catalog
    from apps.reference.models import ReferenceHeading
    from tests.reference.test_catalog import fixture

    spec, rows = fixture()
    spec = replace(spec, source_book_id="622")
    preview = ingest_catalog(spec, rows)
    edition = ingest_catalog(
        spec, rows, dry_run=False, expected_checksum=preview.checksum
    ).edition_id
    return edition, ReferenceHeading.objects.get(edition_id=edition, source_row_id=2).pk


class ExactRecordingRights(TimedMediaRights):
    """Test authority over one accepted immutable asset, never a general media grant."""

    def __init__(self, directory: Directory):
        self.directory = directory
        self.pins = frozenset()
        self.enabled = True
        self.deadline = timezone.now() + timedelta(minutes=30)

    def permits(self, **kw):
        resource = kw["resource"]
        if resource.kind not in {"ATTACHMENT", "ANSWER_MEDIA"}:
            return SourceRightsAdapter().permits(**kw)
        actor = self.directory.resolve(kw["subject_id"])
        return (
            connection.in_atomic_block
            and self.enabled
            and kw["provider_id"] == self.directory.provider_id
            and kw["subject_id"] in {"synthetic-mufti", "synthetic-publisher"}
            and kw["auth_epoch"] == "epoch-1"
            and actor is not None
            and actor.active
            and actor.role == "MUFTI"
            and kw["case_ref"] in self.directory.refs
            and kw["action"] in {"DISCOVER", "READ_MEDIA", "CITE"}
            and timezone.now() < min(self.deadline, self.directory.valid_until)
            and (kw["case_ref"], resource.kind, resource.identifier, resource.sha256) in self.pins
        )

    def grant_deadline(self, **kw):
        return min(self.deadline, self.directory.valid_until) if self.permits(**kw) else None


class ClassificationPolicy(ClassificationAuthority):
    def __init__(self, directory):
        self.directory = directory

    def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
        return (
            provider_id == self.directory.provider_id
            and auth_epoch == "epoch-1"
            and case_ref in self.directory.refs
            and (
                (subject_id == "synthetic-mufti" and action in {"VIEW", "PROPOSE"})
                or (
                    subject_id == "synthetic-publisher"
                    and action in {"VIEW", "APPROVE", "REJECT", "WITHDRAW"}
                )
            )
        )


def inventory(case_id):
    from apps.classification_review.models import ClassificationAction, ClassificationRevision
    from apps.timed_citations.models import TimedCitation, TimedCitationAction

    result = previous_inventory(case_id)
    for model in (TimedCitation, TimedCitationAction, ClassificationRevision, ClassificationAction):
        result["ledger"][model._meta.label] = [
            {
                "id": str(row["id"]),
                "sha256": sha256(
                    json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            for row in model.objects.order_by("id").values()
        ]
    result["timed"] = list(
        TimedCitation.objects.order_by("number").values(
            "number", "snapshot_sha256", "start_ms", "end_ms", "duration_ms"
        )
    )
    result["counts"].update(
        timed_citations=TimedCitation.objects.count(),
        timed_confirmations=TimedCitationAction.objects.filter(action="CONFIRM").count(),
        classifications=ClassificationRevision.objects.count(),
        classification_approvals=ClassificationAction.objects.filter(action="APPROVE").count(),
        classification_rejections=ClassificationAction.objects.filter(action="REJECT").count(),
    )
    return result
