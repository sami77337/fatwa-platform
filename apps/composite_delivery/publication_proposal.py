"""Honest publication handoff for unsupported YouTube audio; no sendable URL."""

from contextlib import contextmanager

from django.conf import settings

from apps.answer_media.editor_boundary import EditorBoundary
from apps.casework import delivery as legacy
from apps.casework import services as cases

from . import services


def enabled():
    return getattr(settings, "FATWA_COMPOSITE_PUBLICATION_PROPOSAL_ENABLED", False) is True


def offered(origin, manifest, plan):
    return (
        enabled()
        and origin["channel"] == "youtube"
        and getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is True
        and any(
            part["kind"] == "AUDIO" and step.action != "READY_FOR_ADAPTER"
            for part, step in zip(manifest["parts"], plan.steps, strict=True)
        )
    )


@contextmanager
def boundary(*, case_id, subject_id, provider, selection_mode=None, synthetic_fixtures_only=False):
    services._enabled()
    if not enabled():
        raise cases.CaseConflict("publication_proposal_disabled")
    identity = services._choice_identity(provider)
    editor = EditorBoundary(provider)
    flag = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False)
    with legacy._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        prepared = services._prepare(case, subject_id, provider, selection_mode)
        yield
        services._reader(case, subject_id, provider, prepared)(case.public_ref)
        editor.check(cases._identity(provider, subject_id, case))
        if (
            not enabled()
            or services._choice_identity(provider) != identity
            or getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is not flag
        ):
            raise cases.CaseConflict("publication_proposal_context_changed")


def prepare(case, prepared):
    origin = cases._delivery_origin_for_locked_case(case)
    if not offered(origin, prepared[1], prepared[4]):
        raise cases.CaseConflict("publication_proposal_not_applicable")
    profile = services._profile(origin["channel"])
    return {
        "status": "EXTERNAL_PUBLICATION_UNAVAILABLE",
        "public_ref": case.public_ref,
        "decision_id": str(prepared[0].pk),
        "manifest_sha256": prepared[1]["sha256"],
        "capability_sha256": prepared[2],
        "origin_channel": origin["channel"],
        "link_capability_verified": "link" in profile.capabilities.supported,
        "independent_publication_review_required": True,
        "external_page_verified": False,
        "sendable": False,
        "automatic_publication": False,
        "public_url": None,
    }
