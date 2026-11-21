"""Real scoped organizer identities, explicit exact resources and generated recording."""

import uuid

from django.test import override_settings
from django.utils import timezone

from apps.answer_media import services as answer_media
from apps.answer_media.models import AnswerPart
from apps.casework import services as cases
from apps.public_answer_media.authority import AnswerMediaAuthority
from apps.public_answer_media.models import RecordingTranscript, TranscriptAction
from apps.public_answer_media.test_support import audio
from apps.timed_citations.rights import TimedMediaRights

from . import transcripts
from .boundary import TRANSCRIPT_ACTIONS, digest, source_rows
from .test_support import FEATURES, Authority, Directory, Profiles, intake

TRANSCRIPT_FEATURES = {
    **FEATURES,
    "FATWA_OPERATIONAL_TRANSCRIPTS_ENABLED": True,
    "FATWA_PUBLIC_ANSWER_MEDIA_ENABLED": True,
}
TEXT = "تفريغ اصطناعي محفوظ. وهذه عبارة للمراجعة البشرية."


class TranscriptAuthority(Authority):
    def __init__(self, receipts):
        super().__init__(receipts)
        self.transcript_rules = set()

    def projection_epoch(self):
        return repr((super().projection_epoch(), sorted(self.transcript_rules)))

    def _allows(self, values):
        r = values["resource"]
        if r["kind"] == "CASE_OPERATIONAL_SECTION":
            return super()._allows(values)
        key = (
            values["subject_id"],
            values["role"],
            values["case_ref"],
            values["action"],
            r["kind"],
            r.get("part_id"),
            r.get("part_sha256"),
        )
        if (
            values["provider_id"] != Directory.provider_id
            or values["auth_epoch"] != "epoch-1"
            or timezone.now() >= self.until
            or key not in self.transcript_rules
            or not AnswerPart.objects.filter(
                pk=r["part_id"],
                sha256=r["part_sha256"],
                manifest__answer__case_id=r["case_id"],
                manifest__answer__case__public_ref=values["case_ref"],
                kind="AUDIO",
            ).exists()
        ):
            return False
        return r["kind"] == "CASE_RECORDING_SOURCE" or (
            r["kind"] == "CASE_RECORDING_TRANSCRIPT"
            and RecordingTranscript.objects.filter(
                pk=r["transcript_id"],
                digest=r["transcript_digest"],
                part_id=r["part_id"],
                case_id=r["case_id"],
            ).exists()
        )

    def revoke(self, *, subject="operator", action=None, case_ref=None):
        super().revoke(subject=subject, action=action, case_ref=case_ref)
        self.transcript_rules = {
            row
            for row in self.transcript_rules
            if not (
                row[0] == subject
                and (action is None or row[3] == action)
                and (case_ref is None or row[2] == case_ref)
            )
        }


class TranscriptDomainAuthority(AnswerMediaAuthority):
    def __init__(self):
        self.rules, self.denied, self.hook = set(), set(), None

    def projection_epoch(self):
        return digest((sorted(self.rules), sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        r = values["resource"]
        key = (
            values["subject_id"],
            values["case_ref"],
            values["action"],
            r.get("part_id"),
            r.get("part_sha256"),
        )
        if (
            values["provider_id"] != Directory.provider_id
            or values["auth_epoch"] != "epoch-1"
            or key not in self.rules
            or (values["subject_id"], values["action"]) in self.denied
            or r.get("edition_id")
            or r.get("edition_digest")
        ):
            return False
        if r.get("transcript_id"):
            return RecordingTranscript.objects.filter(
                pk=r["transcript_id"],
                digest=r["transcript_digest"],
                part_id=r["part_id"],
                case__public_ref=values["case_ref"],
            ).exists()
        return True


class TranscriptMediaRights(TimedMediaRights):
    def __init__(self, until):
        self.until, self.rules, self.denied, self.hook = until, set(), set(), None

    def projection_epoch(self):
        return self.media_projection_epoch()

    def media_projection_epoch(self):
        return digest((sorted(self.rules), sorted(self.denied), self.until.isoformat()))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        r = values["resource"]
        return (
            values["provider_id"] == Directory.provider_id
            and values["auth_epoch"] == "epoch-1"
            and values["action"] == "READ_MEDIA"
            and r.kind == "ANSWER_MEDIA"
            and values["subject_id"] not in self.denied
            and timezone.now() < self.until
            and (values["subject_id"], values["case_ref"], r.identifier, r.sha256) in self.rules
        )

    def grant_deadline(self, **values):
        return self.until if self.permits(**values) else None


def grant_transcripts(authority, domain, rights, receipt, part):
    for subject, role in (
        ("operator", "ORGANIZER"),
        ("admin", "ORGANIZER_ADMIN"),
        ("mufti", "MUFTI"),
    ):
        authority.grants.add(
            (
                subject,
                role,
                receipt["public_ref"],
                "READ_TRANSCRIPT_EDITOR",
                "transcript_editor",
                receipt["case_id"],
            )
        )
        for action in TRANSCRIPT_ACTIONS:
            for kind in ("CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"):
                authority.transcript_rules.add(
                    (subject, role, receipt["public_ref"], action, kind, str(part.pk), part.sha256)
                )
        # Deliberately includes REVIEW_MEANING for organizers: the application
        # must reject it independently of a permissive configured grant.
        for action in transcripts.ACTION_MAP:
            domain.rules.add((subject, receipt["public_ref"], action, str(part.pk), part.sha256))
        rights.rules.add((subject, receipt["public_ref"], str(part.pk), part.sha256))


class TranscriptFixture:
    def setUp(self):
        super().setUp()
        self.target = intake("organizer-transcripts-" + uuid.uuid4().hex)
        self.receipts = {
            "transcripts": {key: self.target[key] for key in ("case_id", "public_ref")},
            "hidden": intake("organizer-transcripts-hidden"),
            "unscoped": intake("organizer-transcripts-unscoped"),
        }
        self.receipts = {
            kind: {key: row[key] for key in ("case_id", "public_ref")}
            for kind, row in self.receipts.items()
        }
        self.directory = Directory(
            [row["public_ref"] for key, row in self.receipts.items() if key != "unscoped"]
        )
        self.authority, self.domain = (
            TranscriptAuthority(self.receipts),
            TranscriptDomainAuthority(),
        )
        self.rights = TranscriptMediaRights(self.authority.until)
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_PUBLIC_ANSWER_MEDIA_AUTHORITY=self.domain,
            FATWA_RESEARCH_WORKSPACE_RIGHTS=self.rights,
            FATWA_COMPOSITE_DELIVERY_CAPABILITIES=Profiles(),
        )
        configured.enable()
        self.addCleanup(configured.disable)
        canonical = dict(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        result = answer_media.save_multipart_answer(
            **canonical,
            text="جواب اصطناعي أصلي من المفتي يبقى محفوظًا",
            files=[{"raw": audio(), "filename": "private-original.wav", "media_type": "audio/wav"}],
            expected_revision=1,
            expected_evidence_version=1,
        )
        self.answer_id = result["answers"][-1]["id"]
        cases.record_decision(
            **canonical,
            answer_id=self.answer_id,
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )
        self.part = AnswerPart.objects.get(manifest__answer_id=self.answer_id, kind="AUDIO")
        grant_transcripts(self.authority, self.domain, self.rights, self.target, self.part)
        self.common = dict(
            subject_id="operator", provider=self.directory, synthetic_fixtures_only=True
        )
        self.originals, self.transcript_originals = (
            self.state(),
            self.immutable_transcript_sources(),
        )

    def state(self):
        return digest(source_rows([row["case_id"] for row in self.receipts.values()]))

    def immutable_transcript_sources(self):
        result = source_rows([row["case_id"] for row in self.receipts.values()])
        for model in (RecordingTranscript, TranscriptAction):
            result.pop(model._meta.db_table)
        return digest(result)

    def save_values(self, **changes):
        last = RecordingTranscript.objects.filter(part=self.part).order_by("-number").first()
        return {
            "case_ref": self.target["public_ref"],
            "part_id": str(self.part.pk),
            "part_sha256": self.part.sha256,
            "text": TEXT,
            "segments": [],
            "change_kind": "EDITORIAL",
            "note": "تفريغ وتنسيق بشري يحفظ الأصل",
            "expected_version": last.number if last else 0,
            "command_id": str(uuid.uuid4()),
            "expected_revision": 3,
            "expected_evidence_version": 1,
            **changes,
        }

    def save_transcript(self, **changes):
        with transcripts.save(**self.common, **self.save_values(**changes)) as result:
            return result

    def review_values(self, row=None, **changes):
        row = row or RecordingTranscript.objects.filter(part=self.part).order_by("-number").first()
        return {
            "case_ref": self.target["public_ref"],
            "transcript_id": str(row.pk),
            "transcript_digest": row.digest,
            "action": "REVIEW",
            "note": "مراجعة بشرية مستقلة",
            "confirmed": True,
            "expected_actions": row.actions.count(),
            "command_id": str(uuid.uuid4()),
            "expected_revision": 3,
            "expected_evidence_version": 1,
            **changes,
        }

    def review_transcript(self, *, subject="admin", **changes):
        with transcripts.decide(
            **{**self.common, "subject_id": subject}, **self.review_values(**changes)
        ) as result:
            return result
