"""Finite synthetic mandates and actual operational use of stored grants."""

import uuid
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.casework import services as cases
from apps.casework.models import Case
from apps.operational_workspace import notes
from apps.operational_workspace.test_support import Directory
from config.settings import campaign_review
from tests.casework.test_http import WEB_SETTINGS

from . import catalog, services, store
from .authority import Grant, PermissionManagementAuthority
from .runtime import StoredOperationalAuthority

FEATURES = {
    **{key: value for key, value in WEB_SETTINGS.items() if not key.startswith("DATA_UPLOAD_")},
    "ROOT_URLCONF": "config.campaign_urls",
    "MIDDLEWARE": list(campaign_review.MIDDLEWARE),
    "FATWA_PERMISSION_SETS_ENABLED": True,
    "FATWA_OPERATIONAL_WORKSPACE_ENABLED": True,
    "FATWA_OPERATIONAL_INTERNAL_NOTES_ENABLED": True,
    "FATWA_CASE_ORGANIZATION_ENABLED": True,
    "FATWA_DATA_PRIVACY_ENABLED": False,
    "FATWA_STAFF_SESSIONS_ENABLED": False,
}


class Authority(PermissionManagementAuthority):
    def __init__(self, directory, resources):
        self.directory = directory
        self.scopes = tuple(resources)
        self.candidates = tuple(sorted(directory.identities))
        self.until = timezone.now() + timedelta(minutes=30)
        self.grants = set()
        self.hook = None
        for actor in ("admin", "mufti"):
            for operation in ("ENTER", "CREATE_SET"):
                self.grants.add((actor, operation, "", "", "", "", ""))
            for subject, target in directory.identities.items():
                self.allow_target(actor, "USER", subject, subject, target.role)

    def allow_target(self, actor, kind, key, subject="", role=""):
        for operation in ("READ_" + kind, "WRITE_" + kind, "READ_AUDIT"):
            self.grants.add((actor, operation, kind, key, subject, role, ""))
        for value in self.scopes:
            for effect in ("ALLOW", "DENY"):
                self.grants.add(
                    (
                        actor,
                        "MANAGE_RULE",
                        kind,
                        key,
                        subject,
                        role,
                        catalog.digest({"scope": value, "effect": effect}),
                    )
                )

    def allow_set(self, key):
        for actor in ("admin", "mufti"):
            self.allow_target(actor, "SET", key)

    def projection_epoch(self):
        return catalog.canonical(
            [sorted(self.grants), self.candidates, self.scopes, self.until.isoformat()]
        )

    def subjects(self, **values):
        return self.candidates

    def resources(self, **values):
        return self.scopes

    def authorize(self, **values):
        key = (
            values["subject_id"],
            values["operation"],
            values["scope_kind"],
            values["scope_key"],
            values["target_subject"],
            values["target_role"],
            catalog.digest(values["resource"]) if values["resource"] is not None else "",
        )
        actor = self.directory.identities.get(values["subject_id"])
        permitted = (
            actor is not None
            and values["provider_id"] == self.directory.provider_id
            and values["role"] == actor.role
            and values["auth_epoch"] == actor.auth_epoch
            and key in self.grants
            and self.until > timezone.now()
        )
        if self.hook:
            self.hook(values)
        return Grant(self.until) if permitted else None

    def revoke(self, operation, *, actor="admin", target=None):
        self.grants = {
            row
            for row in self.grants
            if not (
                row[0] == actor and row[1] == operation and (target is None or row[4] == target)
            )
        }


class Fixture:
    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="أصل سؤال خاص محفوظ لا يحرره مدير الصلاحيات",
            source_event_id="permissions-event-" + suffix,
            requester_id="permissions-requester-" + suffix,
            idempotency_key="permissions-intake-" + suffix,
            synthetic_fixtures_only=True,
        )
        self.directory = Directory([self.receipt["public_ref"]])
        self.directory.provider_id = "synthetic-permission-sets-directory"
        self.scopes = {
            action: {
                "domain": catalog.DOMAIN,
                "case_ref": self.receipt["public_ref"],
                "action": action,
                "resource": {
                    "kind": "CASE_OPERATIONAL_SECTION",
                    "case_id": self.receipt["case_id"],
                    "section": catalog.SECTIONS[action],
                },
            }
            for action in (
                "READ_QUEUE",
                "READ_CASE",
                "READ_METADATA",
                "READ_INTERNAL_NOTES",
                "ADD_INTERNAL_NOTE",
            )
        }
        self.authority = Authority(self.directory, self.scopes.values())
        self.runtime = StoredOperationalAuthority()
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY=self.authority,
            FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=self.runtime,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.base = dict(provider=self.directory, subject_id="admin", synthetic_fixtures_only=True)
        self.operator = {**self.base, "subject_id": "operator"}
        self.template_key = str(uuid.uuid4())
        self.authority.allow_set(self.template_key)
        self.original = Case.objects.get(pk=self.receipt["case_id"]).source.original_question

    def rule(self, action, effect="ALLOW"):
        return {"scope": self.scopes[action], "effect": effect}

    def proposal(
        self, *, kind="SET", key=None, definition=None, change=None, reverted_from=None, **changes
    ):
        key = key or (self.template_key if kind == "SET" else "operator")
        current = store.latest().get((kind, self.directory.provider_id, key))
        if definition is None and change not in {"DISABLE", "REVERT"}:
            definition = (
                {
                    "title": "التنظيم مع الملاحظات",
                    "rules": [self.rule(action) for action in self.scopes],
                }
                if kind == "SET"
                else {"sets": [self.template_key], "overrides": []}
            )
        return {
            "kind": kind,
            "key": key,
            "change": change or ("REPLACE" if current else "CREATE"),
            "definition": definition,
            "expected_digest": current.digest if current else catalog.ZERO,
            "note": "سبب إداري اصطناعي محدد",
            "minutes": 15,
            "request_key": str(uuid.uuid4()),
            "reverted_from": reverted_from,
            **changes,
        }

    def prepare(self, proposal=None, *, base=None, **changes):
        with services.preview(
            proposal=proposal or self.proposal(**changes), **(base or self.base)
        ) as result:
            return result

    def save(self, proposal=None, *, base=None, **changes):
        plan = self.prepare(proposal, base=base, **changes)
        with services.apply(plan=plan, confirmed=True, **(base or self.base)) as result:
            return result["saved"]

    def seeded(self):
        template = self.save()
        user = self.save(kind="USER")
        return template, user

    def allowed(self, action, subject="operator"):
        actor = self.directory.identities[subject]
        value = self.scopes[action]
        return self.runtime.permits(
            provider_id=self.directory.provider_id,
            subject_id=subject,
            role=actor.role,
            auth_epoch=actor.auth_epoch,
            case_ref=value["case_ref"],
            action=action,
            resource=value["resource"],
        )

    def note(self, text="ملاحظة من منظم مخول بقالب محفوظ"):
        case = Case.objects.get(pk=self.receipt["case_id"])
        with notes.projection(case_ref=case.public_ref, **self.operator) as read:
            version = read["metadata_version"]
        with notes.append(
            **self.operator,
            case_ref=case.public_ref,
            note=text,
            command_id=str(uuid.uuid4()),
            expected_metadata_version=version,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
        ) as result:
            return result

    def assert_original(self):
        case = Case.objects.get(pk=self.receipt["case_id"])
        self.assertEqual(case.source.original_question, self.original)
        self.assertEqual(case.revision, 1)
        self.assertEqual(case.evidence_version, 1)
        self.assertEqual(case.answers.count(), 0)
