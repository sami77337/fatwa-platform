"""Restore exact audited definitions, then use an explicitly selected current adapter."""

import json
import unittest
import uuid
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.case_organization.models import OrganizationRevision
from apps.casework import services as cases
from apps.casework.models import Case, CaseEvent, CaseEvidence, CaseSource
from apps.delivery_queue.services import synthetic_queue_atomic
from apps.operational_workspace import notes
from apps.operational_workspace.test_support import Directory

from . import catalog, services
from .models import PermissionRevision
from .runtime import StoredOperationalAuthority
from .test_support import FEATURES, Authority, Fixture

TABLES = (PermissionRevision._meta.db_table,)
FUNCTIONS = ("ps_rule_valid(jsonb)", "ps_revision_guard()")
TRIGGERS = ("ps_revision_guard",)
DENIALS = (
    "feature_disabled",
    "runtime_adapter_absent",
    "directory_absent",
    "target_inactive",
    "target_auth_epoch_changed",
    "target_case_scope_changed",
    "management_authority_absent",
    "management_mandate_revoked",
    "self_grant_rejected",
    "scientific_override_rejected",
    "stored_individual_deny",
    "disabled_template_binding",
)


def fingerprint(values):
    return sha256(json.dumps(list(values), sort_keys=True, default=str).encode()).hexdigest()


def rows(pins):
    values = PermissionRevision.objects.filter(
        provider_id=pins["provider_id"], scope_key__in=(pins["template_key"], "operator")
    ).order_by("kind", "scope_key", "number")
    if values.count() != 6:
        raise AssertionError("Six immutable template/user revisions must survive recovery")
    return {TABLES[0]: fingerprint(values.values())}


def originals(pins):
    identifier = pins["case"]["case_id"]
    return {
        model._meta.db_table: fingerprint(
            model.objects.filter(**{field: identifier}).order_by("pk").values()
        )
        for model, field in (
            (Case, "pk"),
            (CaseSource, "case_id"),
            (CaseEvidence, "case_id"),
            (CaseEvent, "case_id"),
            (OrganizationRevision, "case_id"),
        )
    }


def read(pins, common):
    with notes.projection(case_ref=pins["case"]["public_ref"], **common) as result:
        if result["role"] != "ORGANIZER" or not result["can_read"] or not result["can_add"]:
            raise AssertionError(
                "The current real organizer did not retain the exact restored grant"
            )
        return fingerprint(
            [
                {
                    key: result[key]
                    for key in (
                        "public_ref",
                        "history",
                        "metadata_version",
                        "revision",
                        "evidence_version",
                    )
                }
            ]
        )


def populate():
    class RecoveryFixture(Fixture, unittest.TestCase):
        pass

    fixture = RecoveryFixture()
    with override_settings(**FEATURES):
        try:
            fixture.setUp()
            template = fixture.save(minutes=30)
            user = fixture.save(kind="USER", minutes=30)
            fixture.save(
                kind="USER",
                minutes=30,
                definition={
                    "sets": [fixture.template_key],
                    "overrides": [fixture.rule("ADD_INTERNAL_NOTE", "DENY")],
                },
            )
            fixture.save(kind="USER", minutes=30, change="REVERT", reverted_from=user["id"])
            fixture.save(change="DISABLE", minutes=30)
            fixture.save(change="REVERT", reverted_from=template["id"], minutes=30)
            fixture.note("ملاحظة أصلية بمنحة محفوظة قبل الاستعادة")
            pins = {
                "provider_id": fixture.directory.provider_id,
                "case": {key: fixture.receipt[key] for key in ("case_id", "public_ref")},
                "template_key": fixture.template_key,
                "scopes": list(fixture.scopes.values()),
            }
            pins["expected"] = read(pins, fixture.operator)
            pins["tables"], pins["originals"] = rows(pins), originals(pins)
            return pins
        finally:
            fixture.doCleanups()


@contextmanager
def fresh_trust(pins):
    directory = Directory([pins["case"]["public_ref"]])
    directory.provider_id = pins["provider_id"]
    authority = Authority(directory, pins["scopes"])
    authority.allow_set(pins["template_key"])
    with override_settings(
        **FEATURES,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY=authority,
        FATWA_OPERATIONAL_WORKSPACE_AUTHORITY=StoredOperationalAuthority(),
    ):
        yield directory, authority


def verify_restored(pins):
    def unchanged():
        if rows(pins) != pins["tables"] or originals(pins) != pins["originals"]:
            raise AssertionError("Recovery changed the permission audit or original source history")

    unchanged()
    denied = dict.fromkeys(DENIALS, 0)
    with fresh_trust(pins) as (directory, authority):
        base = dict(provider=directory, subject_id="admin", synthetic_fixtures_only=True)
        operator = {**base, "subject_id": "operator"}

        def positive():
            if read(pins, operator) != pins["expected"]:
                raise AssertionError(
                    "The restored exact grant returned different operational content"
                )

        def deny(name, call):
            try:
                call()
            except cases.CaseConflict:
                denied[name] += 1
            else:
                raise AssertionError("Recovered state inferred missing current permission: " + name)

        def open_notes():
            with notes.projection(case_ref=pins["case"]["public_ref"], **operator):
                pass

        def inspect():
            with services.inspect(kind="USER", key="operator", **base):
                pass

        positive()
        for name, setting, value in (
            ("feature_disabled", "FATWA_PERMISSION_SETS_ENABLED", False),
            ("runtime_adapter_absent", "FATWA_OPERATIONAL_WORKSPACE_AUTHORITY", None),
            ("directory_absent", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{setting: value}):
                deny(name, open_notes)
        original = directory.identities["operator"]
        for name, actor in (
            ("target_inactive", replace(original, active=False)),
            ("target_auth_epoch_changed", replace(original, auth_epoch="epoch-2")),
            (
                "target_case_scope_changed",
                replace(original, case_keys=frozenset({"outside-recovery"})),
            ),
        ):
            directory.identities["operator"] = actor
            deny(name, open_notes)
        directory.identities["operator"] = original
        with override_settings(FATWA_PERMISSION_SETS_MANAGEMENT_AUTHORITY=None):
            deny("management_authority_absent", inspect)
        grants = set(authority.grants)
        authority.revoke("ENTER")
        deny("management_mandate_revoked", inspect)
        authority.grants = grants

        def proposal(kind, key, definition, change="REPLACE"):
            current = (
                PermissionRevision.objects.filter(
                    kind=kind, provider_id=directory.provider_id, scope_key=key
                )
                .order_by("-number")
                .first()
            )
            return {
                "kind": kind,
                "key": key,
                "definition": definition,
                "change": change if current else "CREATE",
                "expected_digest": current.digest if current else catalog.ZERO,
                "note": "تحقق استعادة محدد",
                "minutes": 5,
                "request_key": str(uuid.uuid4()),
            }

        def check(proposed):
            with services.preview(proposal=proposed, **base):
                pass

        deny(
            "self_grant_rejected",
            lambda: check(proposal("USER", "admin", {"sets": [], "overrides": []})),
        )
        forbidden = {
            "scope": {**pins["scopes"][0], "action": "APPROVE_TRANSCRIPT_MEANING"},
            "effect": "ALLOW",
        }
        deny(
            "scientific_override_rejected",
            lambda: check(proposal("USER", "operator", {"sets": [], "overrides": [forbidden]})),
        )
        for name, proposed in (
            (
                "stored_individual_deny",
                proposal(
                    "USER",
                    "operator",
                    {
                        "sets": [pins["template_key"]],
                        "overrides": [
                            {
                                "scope": next(
                                    value
                                    for value in pins["scopes"]
                                    if value["action"] == "READ_CASE"
                                ),
                                "effect": "DENY",
                            }
                        ],
                    },
                ),
            ),
            ("disabled_template_binding", proposal("SET", pins["template_key"], None, "DISABLE")),
        ):
            with synthetic_queue_atomic(), transaction.atomic():
                with services.preview(proposal=proposed, **base) as plan:
                    pass
                with services.apply(plan=plan, confirmed=True, **base):
                    pass
                deny(name, open_notes)
                transaction.set_rollback(True)
        try:
            with transaction.atomic():
                PermissionRevision.objects.filter(provider_id=directory.provider_id).update(
                    note="محو التاريخ"
                )
        except IntegrityError:
            immutable = True
        else:
            raise AssertionError("Restored permission audit lost its append-only trigger")
        # This positive read is after every named denial, using the current
        # actual identity and explicitly configured adapter, not an imported DTO.
        positive()
    unchanged()
    return {
        "status": "PASS",
        "nonempty_tables": len(TABLES),
        "audit_revisions": 6,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "immutable_audit": immutable,
        "actual_operational_role": "ORGANIZER",
        "preserved_originals": True,
        "restored_rows_require_explicit_runtime_and_current_identity": True,
    }
