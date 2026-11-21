"""Explicit finite synthetic choices; these values are not production policy."""

import uuid
from dataclasses import asdict, replace

from django.test import override_settings

from apps.case_assignments.models import AssignmentEvent, PriorityEvent
from apps.casework.models import Case

from . import coordination
from .boundary import digest, source_rows
from .metadata_test_support import MetadataAuthority
from .test_support import FEATURES, Directory, approved

COORDINATION_FEATURES = {
    **FEATURES,
    "FATWA_OPERATIONAL_COORDINATION_ENABLED": True,
    "FATWA_CASE_ASSIGNMENTS_ENABLED": True,
}


class CandidatePolicy:
    def __init__(self):
        self.subjects = ("mufti", "mufti2")
        self.hook = None

    def projection_epoch(self):
        return repr(self.subjects)

    def __call__(self, subject_id, case_ref):
        if self.hook:
            self.hook()
        # A selector that actually keys by identity catches an incompatible
        # caller passing the whole identity object instead of its identifier.
        return {key: self.subjects for key in ("operator", "admin", "mufti", "mufti2")}[subject_id]


class PriorityPolicy:
    def __init__(self):
        self.options = (
            coordination.PriorityOption("fixture_urgent", "عاجل اصطناعي", 0),
            coordination.PriorityOption("fixture_normal", "عادي اصطناعي", 20),
        )
        self.hook = None

    def projection_epoch(self):
        return repr(self.options)

    def __call__(self, actor, case_ref):
        if self.hook:
            self.hook()
        return self.options


def grant_choices(authority, case, candidates, priorities, directory):
    policy_sha = digest(
        {"epoch": priorities.projection_epoch(), "options": [asdict(x) for x in priorities.options]}
    )
    for subject, role in (
        ("operator", "ORGANIZER"),
        ("admin", "ORGANIZER_ADMIN"),
        ("mufti", "MUFTI"),
    ):
        pairs = [("READ_COORDINATION", coordination.resource(case))]
        for target in candidates.subjects:
            pairs.extend(
                [
                    (
                        "SET_PRIMARY",
                        coordination.resource(
                            case,
                            target=target,
                            target_epoch=directory.identities[target].auth_epoch,
                        ),
                    ),
                    ("CLEAR_PRIMARY", coordination.resource(case, target=target)),
                ]
            )
        pairs.extend(
            (
                "SET_PRIORITY",
                coordination.resource(
                    case,
                    priority=option.value,
                    label=option.label,
                    rank=option.rank,
                    policy_sha256=policy_sha,
                ),
            )
            for option in priorities.options
        )
        authority.resources.update(
            (subject, role, case.public_ref, action, digest(resource)) for action, resource in pairs
        )
    return policy_sha


class CoordinationFixture:
    def setUp(self):
        super().setUp()
        self.target, _ = approved("coordination-" + uuid.uuid4().hex)
        self.receipts = {
            "coordination": {key: self.target[key] for key in ("case_id", "public_ref")}
        }
        self.directory = Directory([self.target["public_ref"]])
        self.directory.identities["mufti2"] = replace(
            self.directory.identities["mufti"], subject_id="mufti2"
        )
        self.authority = MetadataAuthority(self.receipts)
        self.candidates, self.priorities = CandidatePolicy(), PriorityPolicy()
        self.common = {
            "subject_id": "operator",
            "provider": self.directory,
            "synthetic_fixtures_only": True,
        }
        self.policy_sha = grant_choices(
            self.authority,
            Case.objects.get(pk=self.target["case_id"]),
            self.candidates,
            self.priorities,
            self.directory,
        )
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.authority,
            FATWA_CASE_ASSIGNMENT_CANDIDATES=self.candidates,
            FATWA_OPERATIONAL_PRIORITY_POLICY=self.priorities,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.originals = self.immutable_sources()

    def immutable_sources(self):
        values = source_rows([self.target["case_id"]])
        values.pop(AssignmentEvent._meta.db_table)
        values.pop(PriorityEvent._meta.db_table)
        return digest(values)

    def view(self, **changes):
        with coordination.projection(
            case_ref=self.target["public_ref"], **{**self.common, **changes}
        ) as row:
            return row

    def values(self, **changes):
        case = Case.objects.get(pk=self.target["case_id"])
        return (
            dict(
                case_ref=case.public_ref,
                reason="سبب إداري بشري واضح",
                confirmed=True,
                command_id=str(uuid.uuid4()),
                expected_version=0,
                expected_revision=case.revision,
                expected_evidence_version=case.evidence_version,
            )
            | changes
        )

    def assign(self, **changes):
        values = self.values(
            **(
                {"action": "SET_PRIMARY", "target_subject": "mufti", "target_epoch": "epoch-1"}
                | changes
            )
        )
        with coordination.assign(**self.common, **values) as row:
            return row

    def prioritize(self, **changes):
        values = self.values(
            **({"value": "fixture_urgent", "policy_sha256": self.policy_sha} | changes)
        )
        with coordination.set_priority(**self.common, **values) as row:
            return row
