"""Actual operational actors edit metadata and bind reviewed provisional concepts."""

import uuid
from contextlib import contextmanager

from django.conf import settings

from apps.case_organization import services as organization
from apps.casework import services as cases
from apps.development_taxonomy import services as taxonomy
from apps.development_taxonomy.boundary import policy as taxonomy_policy
from apps.development_taxonomy.models import CaseClassification, TreeVersion

from .boundary import scope


class TaxonomyBridge:
    """Reuse taxonomy validators with independently current operational authority.

    No call supplies or changes a MUFTI identity. Source, tree and exact actor
    grants must all pass, and the domain policy stays pinned after all callbacks.
    """

    def __init__(self, guard):
        self.guard = guard
        self.actor, self.provider, self.locked = guard.actor, guard.provider, guard.locked
        self.enabled = getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_ENABLED", False)
        self.configured = getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY", None)
        self.policy, self.epoch = taxonomy_policy() if self.enabled is True else (None, None)
        self.checks = []
        guard.adapters.append(self)

    def permit(self, case_id, action, resource=None, *, required=True):
        case = self.locked.get(cases._uuid(case_id))
        if case is None or self.policy is None or action not in {"READ", "USE", "BIND"}:
            raise cases.CaseConflict("operational_classification_unavailable")
        self.guard.permit(case, "READ_CASE", "case", required=True)
        values = dict(
            provider_id=self.guard.provider_id,
            subject_id=self.actor.subject_id,
            auth_epoch=self.actor.auth_epoch,
            case_ref=case.public_ref,
            action=action,
            resource=resource or {"case_id": str(case.pk)},
        )
        allowed = self.call(values)
        self.checks.append((values, allowed))
        if required and not allowed:
            raise cases.CaseConflict("operational_classification_denied")
        return allowed

    def call(self, values):
        try:
            return self.policy.permits(**{**values, "resource": dict(values["resource"])}) is True
        except Exception as exc:
            raise cases.CaseConflict("operational_classification_policy_unavailable") from exc

    def callbacks(self):
        for values, allowed in self.checks:
            if self.call(values) != allowed:
                raise cases.CaseConflict("operational_classification_grant_changed")

    def final_pins(self):
        if (
            getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_ENABLED", False) is not self.enabled
            or getattr(settings, "FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY", None)
            is not self.configured
        ):
            raise cases.CaseConflict("operational_classification_policy_changed")
        if self.policy is not None:
            current, epoch = taxonomy_policy()
            if current is not self.policy or epoch != self.epoch:
                raise cases.CaseConflict("operational_classification_policy_changed")


def available(case, guard):
    return guard.metadata_feature and guard.permit(case, "READ_METADATA", "metadata")


def _case(case_ref, guard):
    if type(case_ref) is not str or not 1 <= len(case_ref) <= 128 or not guard.metadata_feature:
        raise cases.CaseConflict("operational_metadata_unavailable")
    case = next((row for row in guard.locked.values() if row.public_ref == case_ref), None)
    if case is None:
        raise cases.CaseConflict("operational_metadata_unavailable")
    guard.permit(case, "READ_CASE", "case", required=True)
    guard.permit(case, "READ_METADATA", "metadata", required=True)
    cases._verify(case)
    return case


def resource(case, version):
    return {
        "kind": "CASE_CLASSIFICATION_VERSION",
        "case_id": str(case.pk),
        "tree_case_id": str(version.tree.case_id),
        "tree_id": str(version.tree_id),
        "version_id": str(version.pk),
        "digest": version.digest,
    }


def _versions(case, guard, bridge):
    if bridge.policy is None:
        return []
    versions = list(
        TreeVersion.objects.select_related("tree")
        .filter(tree__case_id__in=guard.locked, humanreview__action="APPROVE")
        .order_by("tree_id", "number")[:65]
    )
    if len(versions) > 64:
        raise cases.CaseConflict("operational_classification_bound")
    result = []
    for row in versions:
        owner = guard.locked[row.tree.case_id]
        if not guard.permit(owner, "READ_CASE", "case") or not guard.permit_resource(
            case, "READ_CLASSIFICATION", resource(case, row)
        ):
            continue
        tree_resource = {"kind": "TREE", "id": str(row.tree_id), "digest": row.tree.digest}
        if not bridge.permit(owner.pk, "READ", tree_resource, required=False):
            continue
        version = taxonomy._version(bridge, row.pk, reviewed=True)
        dto = taxonomy.version_dto(bridge, version)
        dto["can_bind"] = bool(
            case.stage == "ANSWERED"
            and case.approved_answer_id
            and guard.permit_resource(case, "BIND_CLASSIFICATION", resource(case, version))
            and bridge.permit(owner.pk, "USE", tree_resource, required=False)
            and bridge.permit(
                case.pk,
                "BIND",
                {"version": str(version.pk), "digest": version.digest},
                required=False,
            )
        )
        result.append(dto)
    return result


def _projection(case, guard, bridge, *, saved=False):
    history = organization._rows(case)
    latest = history[-1] if history else None
    versions = _versions(case, guard, bridge)
    binding = taxonomy._current(case.pk)
    visible = {row["id"] for row in versions}
    current = None
    if (
        binding is not None
        and str(binding.version_id) in visible
        and bridge.permit(
            case.pk,
            "READ",
            {"kind": "BINDING", "id": str(binding.pk), "digest": binding.digest},
            required=False,
        )
    ):
        current = {
            "version_id": str(binding.version_id),
            "primary": str(binding.primary_id),
            "additional": list(binding.additional),
            "reason": binding.reason,
            "subject_id": binding.subject_id,
            "current": binding.answer_id == case.approved_answer_id
            and binding.evidence_version == case.evidence_version,
        }
    types = latest.question_types if latest else []
    return {
        "public_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "subject": guard.actor.subject_id,
        "role": guard.actor.role,
        "metadata_version": latest.version if latest else 0,
        "classification_version": binding.sequence if binding else 0,
        "command_id": str(uuid.uuid4()),
        "tags": latest.tags if latest else [],
        "tags_text": "\n".join(latest.tags) if latest else "",
        "question_types": types,
        "type_options": [
            {"key": key, "label": label, "selected": key in types}
            for key, label in organization.QUESTION_TYPES.items()
        ],
        "can_edit_tags": guard.permit(case, "EDIT_TAGS", "metadata"),
        "can_edit_types": guard.permit(case, "EDIT_QUESTION_TYPES", "metadata"),
        "classifications": versions,
        "current_classification": current,
        "saved": saved,
    }


@contextmanager
def projection(*, case_ref, **common):
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = TaxonomyBridge(guard)
        yield _projection(case, guard, bridge)


@contextmanager
def update(
    *,
    case_ref,
    field,
    values,
    command_id,
    expected_metadata_version,
    expected_revision,
    expected_evidence_version,
    **common,
):
    if field not in {"tags", "question_types"}:
        raise cases.CaseConflict("operational_metadata_field_unavailable")
    if type(expected_metadata_version) is not int or not 0 <= expected_metadata_version < 256:
        raise cases.CaseConflict("organization_version_invalid")
    cases._mutation_versions(expected_revision, expected_evidence_version)
    command = cases._uuid(command_id)
    command_sha = organization._digest(
        {
            "action": "operational_metadata",
            "field": field,
            "values": values,
            "version": expected_metadata_version,
            "revision": expected_revision,
            "evidence_version": expected_evidence_version,
        }
    )
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = TaxonomyBridge(guard)
        guard.permit(
            case,
            "EDIT_TAGS" if field == "tags" else "EDIT_QUESTION_TYPES",
            "metadata",
            required=True,
        )
        history = organization._rows(case)
        last = history[-1] if history else None
        value = organization._values(
            values if field == "tags" else list(last.tags) if last else [],
            values if field == "question_types" else list(last.question_types) if last else [],
            "",
        )
        guard.finish()
        _, row = organization._append_locked(
            case=case,
            actor=guard.actor,
            provider_id=guard.provider_id,
            value=value,
            command=command,
            command_sha=command_sha,
            expected_metadata_version=expected_metadata_version,
            expected_revision=expected_revision,
            expected_evidence_version=expected_evidence_version,
        )
        if row is not None:
            guard.account_for_append(row)
        yield _projection(case, guard, bridge, saved=True)


@contextmanager
def bind_classification(
    *,
    case_ref,
    version_id,
    version_digest,
    primary,
    additional,
    reason,
    confirmed,
    command_id,
    expected_classification_version,
    expected_revision,
    expected_evidence_version,
    **common,
):
    if confirmed is not True:
        raise cases.CaseConflict("operational_classification_confirmation_required")
    taxonomy.text(reason, 2000)
    command = cases._uuid(command_id)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if (
        type(expected_classification_version) is not int
        or not 0 <= expected_classification_version < 2048
    ):
        raise cases.CaseConflict("operational_classification_version_invalid")
    with scope(**common) as guard:
        case = _case(case_ref, guard)
        bridge = TaxonomyBridge(guard)
        # Resolve only within the locked scope before any version is exposed.
        version = (
            TreeVersion.objects.select_related("tree")
            .filter(
                pk=cases._uuid(version_id),
                tree__case_id__in=guard.locked,
            )
            .first()
        )
        if version is None or version.digest != version_digest:
            raise cases.CaseConflict("operational_classification_source_changed")
        for action in ("READ_CLASSIFICATION", "BIND_CLASSIFICATION"):
            guard.permit_resource(case, action, resource(case, version), required=True)
        version = taxonomy._version(bridge, version.pk, reviewed=True, action="USE")
        taxonomy._approved_case(bridge, case.pk)
        bridge.permit(case.pk, "BIND", {"version": str(version.pk), "digest": version.digest})
        primary, additional = taxonomy._selection(version, primary, additional)
        cases._versions(case, expected_revision, expected_evidence_version)
        previous = taxonomy._current(case.pk)
        replay = CaseClassification.objects.filter(request_key=command).first()
        expected = dict(
            case_id=case.pk,
            answer_id=case.approved_answer_id,
            evidence_version=case.evidence_version,
            version_id=version.pk,
            primary_id=cases._uuid(primary),
            additional=additional,
            reason=reason,
            subject_id=guard.actor.subject_id,
            provider_id=guard.provider_id,
            auth_epoch=guard.actor.auth_epoch,
            sequence=expected_classification_version + 1,
        )
        if replay is not None:
            if (
                previous is None
                or replay.pk != previous.pk
                or any(getattr(replay, key) != value for key, value in expected.items())
            ):
                raise cases.CaseConflict("operational_classification_command_reused")
        else:
            if (previous.sequence if previous else 0) != expected_classification_version:
                raise cases.CaseConflict("operational_classification_version_changed")
            guard.finish()
            row = taxonomy._append_binding_locked(
                case=case,
                version=version,
                primary=primary,
                additional=additional,
                reason=reason,
                request_key=command,
                actor_values={
                    key: expected[key] for key in ("subject_id", "provider_id", "auth_epoch")
                },
            )
            guard.account_for_append(row)
        yield _projection(case, guard, bridge, saved=True)
