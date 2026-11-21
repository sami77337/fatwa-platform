"""Human phrase selection, exact historical sources, review and readable export."""

from apps.casework import services as cases
from apps.casework.models import AnswerRevision
from apps.platform_recovery.integration import mutation_service

from . import sources
from .boundary import digest, scope, seal, verify
from .models import CitationAnchor, CitationReview, CitationSet

MAX_ANCHORS = 12


def occurrences(text, phrase):
    cases._text(text)
    sources.text(phrase, 2000)
    result, start = [], 0
    while len(result) < 64:
        found = text.find(phrase, start)
        if found < 0:
            return result
        result.append(
            {
                "start": found,
                "end": found + len(phrase),
                "context": text[max(0, found - 40) : found + len(phrase) + 40],
            }
        )
        start = found + 1
    raise cases.CaseConflict("precise_citation_occurrence_bound")


def anchor(text, *, start, end, phrase, source, previous_id="", correction_reason=""):
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or text[start:end] != phrase
    ):
        raise cases.CaseConflict("precise_citation_phrase_changed")
    sources.text(phrase, 2000)
    sources.text(correction_reason, 2000, optional=not previous_id)
    sources.validate_pin(source)
    if previous_id:
        cases._uuid(previous_id)
    return dict(
        start=start,
        end=end,
        phrase=phrase,
        source=source,
        previous_id=previous_id,
        correction_reason=correction_reason,
    )


def current(guard, case_id):
    from apps.data_privacy.integration import staff_case

    row, actor = guard.permit(case_id, "READ")
    row.refresh_from_db()
    # This DTO also consumes the original question and copied intake evidence,
    # so retain the same exact-source gates as the canonical case reader.
    with staff_case(row, actor, guard.provider):
        return cases._staff(row)


def verify_set(row):
    verify(row)
    answer = row.answer
    if answer.text_sha256 != cases._digest(answer.text):
        raise cases.CaseConflict("precise_citation_answer_changed")
    entries = list(row.anchors.order_by("ordinal"))
    if len(entries) != row.count:
        raise cases.CaseConflict("precise_citation_set_incomplete")
    for ordinal, entry in enumerate(entries, 1):
        verify(entry)
        if entry.ordinal != ordinal or entry.source_case_id != (
            cases._uuid(entry.source["case_id"]) if entry.source["case_id"] else None
        ):
            raise cases.CaseConflict("precise_citation_order_or_owner_changed")
        anchor(
            answer.text,
            start=entry.start,
            end=entry.end,
            phrase=entry.phrase,
            source=entry.source,
            previous_id=str(entry.previous_id) if entry.previous_id else "",
            correction_reason=entry.correction_reason,
        )
    review = CitationReview.objects.filter(citation_set=row).first()
    if review:
        verify(review)
        if review.content_digest != row.digest or (review.provider_id, review.subject_id) == (
            row.provider_id,
            row.subject_id,
        ):
            raise cases.CaseConflict("precise_citation_review_invalid")
    return entries, review


def read_locked(guard, *, case_id, set_id, usage="READ", require_review=False):
    guard.permit(case_id, "EXPORT" if usage == "EXPORT" else "READ", "CITATIONS", set_id)
    row = (
        CitationSet.objects.select_related("answer")
        .filter(pk=cases._uuid(set_id), answer__case_id=case_id)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("precise_citation_set_unavailable")
    guard.original(case_id, "ANSWER", row.answer_id, action=usage)
    entries, review = verify_set(row)
    if require_review and (review is None or review.action != "APPROVE"):
        raise cases.CaseConflict("precise_citation_human_review_required")
    rendered = []
    for entry in entries:
        live = sources.read(guard, entry.source, owner_case_id=case_id, usage=usage)
        rendered.append(
            {
                "id": str(entry.pk),
                "ordinal": entry.ordinal,
                "start": entry.start,
                "end": entry.end,
                "phrase": entry.phrase,
                "source": entry.source,
                "reference": live["reference"],
                "limitation": live["limitation"],
                "corrections": live["corrections"],
                "added_by": entry.subject_id,
                "added_at": entry.created_at,
                "previous_id": str(entry.previous_id) if entry.previous_id else "",
                "correction_reason": entry.correction_reason,
                "url": f"/casework/precise-citations/sources/{entry.pk}/",
            }
        )
    return {
        "id": str(row.pk),
        "answer_id": str(row.answer_id),
        "answer_revision": row.answer.revision,
        "answer_text": row.answer.text,
        "evidence_version": row.answer.evidence_version,
        "digest": row.digest,
        "entries": rendered,
        "author": row.subject_id,
        "created_at": row.created_at,
        "previous_id": str(row.previous_id) if row.previous_id else "",
        "review": (
            {
                "action": review.action,
                "actor": review.subject_id,
                "note": review.note,
                "created_at": review.created_at,
            }
            if review
            else None
        ),
    }


def saved_projection(guard, case_id, record):
    """A new revision awaits explicit classification; a write grants no content read."""
    from apps.data_privacy.services import PrivacyDenied

    try:
        guard.original(case_id, "ANSWER", record.answer_id)
    except PrivacyDenied:
        return {
            "id": str(record.pk),
            "answer_id": str(record.answer_id),
            "answer_revision": record.answer.revision,
            "classification_required": True,
        }
    return read_locked(guard, case_id=case_id, set_id=record.pk)


@mutation_service
def save(
    *,
    text,
    selections,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    if confirmed is not True:
        raise cases.CaseConflict("precise_citation_human_confirmation_required")
    cases._text(text)
    cases._mutation_versions(expected_revision, expected_evidence_version)
    if type(selections) is not list or not 1 <= len(selections) <= MAX_ANCHORS:
        raise cases.CaseConflict("precise_citation_selection_bound")
    key = cases._uuid(request_key)
    requested = digest(
        [text, selections, expected_revision, expected_evidence_version, str(base["case_id"])]
    )
    with scope(**base) as guard:
        case, actor = guard.permit(base["case_id"], "EDIT")
        replay = CitationSet.objects.filter(request_key=key).first()
        if replay:
            if (
                replay.request_digest != requested
                or replay.answer.case_id != case.pk
                or replay.provider_id != base["provider"].provider_id
                or replay.subject_id != actor.subject_id
            ):
                raise cases.CaseConflict("precise_citation_request_conflict")
            return saved_projection(guard, case.pk, replay)
        cases._versions(case, expected_revision, expected_evidence_version)
        if case.stage == "NEEDS_CLARIFICATION":
            raise cases.CaseConflict("requester_clarification_still_required")
        previous_answer = case.answers.order_by("-revision").first()
        previous = CitationSet.objects.filter(answer=previous_answer).first()
        checked, lineage = [], set()
        for selected in selections:
            if type(selected) is not dict or set(selected) != {
                "start",
                "end",
                "phrase",
                "source",
                "previous_id",
                "correction_reason",
            }:
                raise cases.CaseConflict("precise_citation_selection_invalid")
            entry = anchor(text, **selected)
            sources.read(guard, entry["source"], owner_case_id=case.pk)
            old = None
            if entry["previous_id"]:
                old = CitationAnchor.objects.filter(
                    pk=cases._uuid(entry["previous_id"]), citation_set=previous
                ).first()
                if old is None or old.pk in lineage:
                    raise cases.CaseConflict("precise_citation_correction_lineage")
                verify(old)
                lineage.add(old.pk)
            checked.append((entry, old))
        guard.final_pins()
        case.refresh_from_db()
        cases._versions(case, expected_revision, expected_evidence_version)
        case.answer_revision += 1
        answer = AnswerRevision.objects.create(
            case=case,
            revision=case.answer_revision,
            evidence_version=case.evidence_version,
            text=text,
            text_sha256=cases._digest(text),
            provider_id=base["provider"].provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
        )
        case.stage, case.approved_answer = "UNDER_REVIEW", None
        cases._event(case, "SAVE_ANSWER", actor.subject_id, answer=answer)
        if previous_answer is not None:
            from apps.answer_media.services import clone_parts_for_new_answer
            from apps.case_citations.services import clone_citations_for_new_answer

            clone_parts_for_new_answer(previous_answer, answer)
            clone_citations_for_new_answer(previous_answer, answer)
        author = dict(
            provider_id=base["provider"].provider_id,
            subject_id=actor.subject_id,
            auth_epoch=actor.auth_epoch,
        )
        record = seal(
            CitationSet(
                answer=answer,
                previous=previous,
                request_key=key,
                request_digest=requested,
                count=len(checked),
                **author,
            )
        )
        for ordinal, (entry, old) in enumerate(checked, 1):
            seal(
                CitationAnchor(
                    citation_set=record,
                    ordinal=ordinal,
                    start=entry["start"],
                    end=entry["end"],
                    phrase=entry["phrase"],
                    source=entry["source"],
                    source_case_id=entry["source"]["case_id"] or None,
                    previous=old,
                    correction_reason=entry["correction_reason"],
                    **author,
                )
            )
        guard.written(case.pk)
        # The new canonical revision is intentional; existing library source rows
        # and use decisions retain their original pins, including this same case.
        return saved_projection(guard, case.pk, record)


@mutation_service
def review(
    *,
    set_id,
    action,
    note,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    if confirmed is not True or action not in {"APPROVE", "REJECT"}:
        raise cases.CaseConflict("precise_citation_review_confirmation_required")
    sources.text(note, 2000)
    with scope(**base) as guard:
        case, actor = guard.permit(base["case_id"], "REVIEW", "CITATIONS", set_id)
        cases._versions(case, expected_revision, expected_evidence_version)
        row = (
            CitationSet.objects.select_related("answer")
            .filter(
                pk=cases._uuid(set_id),
                answer__case=case,
                answer__revision=case.answer_revision,
                answer__evidence_version=case.evidence_version,
            )
            .first()
        )
        if row is None:
            raise cases.CaseConflict("precise_citation_current_revision_required")
        read_locked(guard, case_id=case.pk, set_id=row.pk)
        if (row.provider_id, row.subject_id) == (base["provider"].provider_id, actor.subject_id):
            raise cases.CaseConflict("precise_citation_independent_reviewer_required")
        key = cases._uuid(request_key)
        guard.final_pins()
        old = CitationReview.objects.filter(citation_set=row).first()
        if old:
            if (old.request_key, old.action, old.note, old.subject_id, old.provider_id) != (
                key,
                action,
                note,
                actor.subject_id,
                base["provider"].provider_id,
            ):
                raise cases.CaseConflict("precise_citation_review_already_recorded")
        else:
            seal(
                CitationReview(
                    citation_set=row,
                    action=action,
                    note=note,
                    content_digest=row.digest,
                    request_key=key,
                    provider_id=base["provider"].provider_id,
                    subject_id=actor.subject_id,
                    auth_epoch=actor.auth_epoch,
                )
            )
        guard.written(case.pk)
        return read_locked(guard, case_id=case.pk, set_id=row.pk)


@mutation_service
def read(*, set_id, usage="READ", **base):
    if usage not in {"READ", "EXPORT"}:
        raise cases.CaseConflict("precise_citation_usage_invalid")
    with scope(**base) as guard:
        return read_locked(
            guard,
            case_id=base["case_id"],
            set_id=set_id,
            usage=usage,
            require_review=usage == "EXPORT",
        )
