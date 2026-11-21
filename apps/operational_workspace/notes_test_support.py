"""Explicit synthetic note grants, never a role-derived application policy."""

import uuid
from dataclasses import replace

from apps.case_organization import services as organization
from apps.case_organization.models import OrganizationRevision
from apps.casework.models import Case

from . import notes
from .boundary import NOTE_ACTIONS, digest, source_rows
from .test_support import FEATURES, Authority, OperationalFixture, approved

NOTE_FEATURES = {
    **FEATURES,
    "FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED": True,
    "FATWA_REQUESTER_PORTAL_ENABLED": True,
}


def grant_notes(authority, receipts):
    authority.grants.update(
        (subject, role, row["public_ref"], action, "internal_notes", row["case_id"])
        for subject, role in (
            ("operator", "ORGANIZER"),
            ("admin", "ORGANIZER_ADMIN"),
            ("mufti", "MUFTI"),
        )
        for key, row in receipts.items()
        if key not in {"hidden", "unscoped"}
        for action in NOTE_ACTIONS
    )


class NoteFixture(OperationalFixture):
    def setUp(self):
        super().setUp()
        self.target, _common = approved("operational-notes-" + uuid.uuid4().hex)
        self.receipts["notes"] = {key: self.target[key] for key in ("case_id", "public_ref")}
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=frozenset([*actor.case_keys, self.target["public_ref"]])
            )
        self.authority.grants.update(Authority({"notes": self.target}).grants)
        organization.save(
            case_id=self.target["case_id"],
            subject_id="mufti",
            provider=self.directory,
            tags=["وسم تنظيمي محفوظ"],
            question_types=["EDUCATION"],
            note="ملاحظة داخلية لا تعرضها قائمة التشغيل",
            command_id=uuid.uuid4(),
            expected_metadata_version=0,
            expected_revision=3,
            expected_evidence_version=1,
            synthetic_fixtures_only=True,
        )
        grant_notes(self.authority, self.receipts)
        self.originals = self.state()
        self.note_originals = self.immutable_state()

    def immutable_state(self):
        values = source_rows([row["case_id"] for row in self.receipts.values()])
        values.pop(OrganizationRevision._meta.db_table)
        return digest(values)

    def note_values(self, **changes):
        case = Case.objects.get(pk=self.target["case_id"])
        latest = OrganizationRevision.objects.filter(case=case).order_by("-version").first()
        return {
            "case_ref": case.public_ref,
            "note": "ملاحظة من المنظم تبقى داخلية <script>خاص</script>",
            "command_id": str(uuid.uuid4()),
            "expected_metadata_version": latest.version if latest else 0,
            "expected_revision": case.revision,
            "expected_evidence_version": case.evidence_version,
            **changes,
        }

    def append_note(self, **changes):
        with notes.append(**self.common, **self.note_values(**changes)) as result:
            return result
