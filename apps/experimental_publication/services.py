"""Closed editorial publication workflow over the canonical approved case answer."""

import json
import os
from hashlib import sha256

from django.apps import apps
from django.conf import settings

from apps.casework import services as cases
from apps.editorial_search.query_terms import normalize_editorial_search

from .authority import PublicationAuthority
from .models import PublicationAction, PublicationEdition


def _enabled():
    if (
        os.environ.get("FATWA_PRODUCTION") != "0"
        or getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_ENABLED", False) is not True
    ):
        raise cases.CaseConflict("experimental_publication_disabled")


def _authority(identity, provider, case, action):
    authority = getattr(settings, "FATWA_EXPERIMENTAL_PUBLICATION_AUTHORITY", None)
    if not isinstance(authority, PublicationAuthority):
        raise cases.CaseConflict("publication_authority_required")
    try:
        allowed = authority.permits(
            provider_id=provider.provider_id,
            subject_id=identity.subject_id,
            auth_epoch=identity.auth_epoch,
            case_ref=case.public_ref,
            action=action,
        )
    except Exception as exc:
        raise cases.CaseConflict("publication_authority_unavailable") from exc
    if allowed is not True:
        raise cases.CaseConflict("publication_action_denied")


def _approved(case, edition=None):
    if case.stage != "ANSWERED" or not case.approved_answer_id:
        raise cases.CaseConflict("current_approval_required")
    answer = case.answers.get(pk=case.approved_answer_id)
    decision = answer.decision
    if (
        answer.evidence_version != case.evidence_version
        or decision.action != "APPROVE"
        or decision.evidence_version != case.evidence_version
        or (
            edition is not None
            and (
                edition.answer_id != answer.pk
                or edition.decision_id != decision.pk
                or edition.evidence_version != case.evidence_version
            )
        )
    ):
        raise cases.CaseConflict("publication_source_changed")
    return answer, decision


def _digest(title, category, body, citations):
    return sha256(
        json.dumps(
            [title, category, body, citations],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _verify(edition):
    if edition.content_sha256 != _digest(
        edition.title, edition.category, edition.body, edition.citations
    ):
        raise cases.CaseConflict("publication_content_changed")


def _citation_snapshot(answer):
    # The citation app supplies only source-pinned, human-verified references.
    # Without that optional app there is no free-form citation input fallback.
    if not apps.is_installed("apps.case_citations"):
        return []
    from apps.case_citations.services import citations_for_locked_answer

    return [
        {"source": item["source"], "source_sha256": item["source_sha256"]}
        for item in citations_for_locked_answer(answer)
    ]


def _projection(edition, *, editorial=False):
    _verify(edition)
    actions = set(edition.actions.values_list("action", flat=True))
    result = {
        "id": str(edition.pk),
        "number": edition.number,
        "title": edition.title,
        "category": edition.category,
        "body": edition.body,
        "citations": edition.citations,
        "state": "WITHDRAWN"
        if "WITHDRAW" in actions
        else (
            "PUBLISHED"
            if "APPROVE" in actions
            else ("REVIEWED" if "REVIEW" in actions else "CANDIDATE")
        ),
    }
    if editorial:
        result.update(
            source_answer_revision=edition.answer.revision,
            evidence_version=edition.evidence_version,
            content_sha256=edition.content_sha256,
        )
    # Deliberately no case reference, original question, actor, internal note or audit.
    return result


def create_edition(
    *,
    case_id,
    subject_id,
    provider,
    expected_revision,
    expected_evidence_version,
    title,
    category,
    body,
    synthetic_fixtures_only=False,
):
    _enabled()
    for value, maximum in ((title, 160), (category, 80), (body, cases.MAX_TEXT)):
        cases._text(value)
        if len(value) > maximum:
            raise cases.CaseConflict("publication_text_too_long")
    with cases._staff_case(
        case_id,
        subject_id,
        provider,
        synthetic_fixtures_only,
        expected_revision=expected_revision,
        expected_evidence_version=expected_evidence_version,
    ) as (case, identity):
        answer, decision = _approved(case)
        number = PublicationEdition.objects.filter(case=case).count() + 1
        if number > 64:
            raise cases.CaseConflict("publication_capacity")
        citations = _citation_snapshot(answer)
        edition = PublicationEdition.objects.create(
            case=case,
            answer=answer,
            decision=decision,
            number=number,
            evidence_version=case.evidence_version,
            title=title,
            category=category,
            body=body,
            citations=citations,
            content_sha256=_digest(title, category, body, citations),
            subject_id=identity.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=identity.auth_epoch,
        )
        return _projection(edition, editorial=True)


def act(
    *,
    case_id,
    edition_id,
    subject_id,
    provider,
    action,
    reviewed=False,
    synthetic_fixtures_only=False,
):
    _enabled()
    if action not in {"REVIEW", "APPROVE", "WITHDRAW"}:
        raise cases.CaseConflict("publication_action_invalid")
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor):
        edition = PublicationEdition.objects.filter(pk=cases._uuid(edition_id), case=case).first()
        if edition is None:
            raise cases.CaseConflict("publication_unavailable")
        _verify(edition)
        existing = set(edition.actions.values_list("action", flat=True))
        if action in existing or "WITHDRAW" in existing:
            raise cases.CaseConflict("publication_transition_invalid")
        if action == "WITHDRAW":
            _authority(actor, provider, case, action)
        else:
            answer, decision = _approved(case, edition)
            if edition.citations != _citation_snapshot(answer):
                raise cases.CaseConflict("publication_citation_source_changed")
            if edition.number != PublicationEdition.objects.filter(case=case).count():
                raise cases.CaseConflict("publication_edition_changed")
            if action == "REVIEW":
                if reviewed is not True or existing:
                    raise cases.CaseConflict("explicit_redaction_review_required")
            else:
                _authority(actor, provider, case, action)
                if existing != {"REVIEW"}:
                    raise cases.CaseConflict("redaction_review_required")
                reviewer = edition.actions.get(action="REVIEW")
                actors = {
                    (edition.provider_id, edition.subject_id),
                    (decision.provider_id, decision.subject_id),
                    (reviewer.provider_id, reviewer.subject_id),
                }
                if (provider.provider_id, actor.subject_id) in actors:
                    raise cases.CaseConflict("independent_publication_approver_required")
        current = cases._identity(provider, subject_id, case)
        if current.auth_epoch != actor.auth_epoch:
            raise cases.CaseConflict("publication_identity_changed")
        PublicationAction.objects.create(
            edition=edition,
            action=action,
            subject_id=actor.subject_id,
            provider_id=provider.provider_id,
            auth_epoch=actor.auth_epoch,
        )
        return _projection(edition, editorial=True)


def desk(*, case_id, subject_id, provider, synthetic_fixtures_only=False):
    _enabled()
    with cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, _):
        current = None
        if case.approved_answer_id:
            answer, _ = _approved(case)
            current = {"text": answer.text, "revision": answer.revision}
        return {
            "public_ref": case.public_ref,
            "case_id": str(case.pk),
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "approved": current,
            "editions": [
                _projection(e, editorial=True)
                for e in PublicationEdition.objects.filter(case=case).order_by("-number")
            ],
        }


def library(*, subject_id, provider, query="", synthetic_fixtures_only=False):
    _enabled()
    cases._text(query, optional=True)
    if len(query) > 80:
        raise cases.CaseConflict("publication_query_too_long")
    query = normalize_editorial_search(query)
    scoped = cases.list_cases(
        subject_id=subject_id, provider=provider, synthetic_fixtures_only=synthetic_fixtures_only
    )
    output = []
    for row in scoped:
        with cases._staff_case(row["case_id"], subject_id, provider, True) as (case, _):
            # The most recently approved edition is authoritative; withdrawal never
            # resurrects an older publication. Unapproved candidates are never searched.
            edition = (
                PublicationEdition.objects.filter(case=case, actions__action="APPROVE")
                .order_by("-number")
                .first()
            )
            if edition is None or edition.actions.filter(action="WITHDRAW").exists():
                continue
            try:
                _approved(case, edition)
                _verify(edition)
                if edition.citations != _citation_snapshot(edition.answer):
                    continue
            except cases.CaseConflict:
                continue
            public = _projection(edition)
            haystack = normalize_editorial_search(
                " ".join((public["title"], public["category"], public["body"]))
            )
            if not query or query in haystack:
                output.append(public)
    return output
