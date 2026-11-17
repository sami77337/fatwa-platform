"""Project existing immutable events; persist only the user's explicit seen marker."""

from apps.casework import services as casework

from .models import SeenUpdate

KINDS = {
    "INTAKE": "سؤال جديد",
    "FOLLOWUP": "تعقيب جديد وتحديث للوقائع",
    "SAVE_ANSWER": "إصدار جواب بشري جديد",
    "RETURN_FOR_CHANGES": "أُعيد جواب للتعديل",
}


def read_inbox(*, subject_id, provider, synthetic_fixtures_only=False):
    rows = casework.list_cases(subject_id=subject_id, provider=provider,
                               synthetic_fixtures_only=synthetic_fixtures_only)
    updates = []
    for row in rows:
        # Same scoped, locked, integrity-checked read boundary as the current case API.
        with casework._staff_case(row["case_id"], subject_id, provider,
                                 synthetic_fixtures_only) as (case, identity):
            seen = set(SeenUpdate.objects.filter(
                event__case=case, provider_id=provider.provider_id, subject_id=identity.subject_id,
            ).values_list("event_id", flat=True))
            for event in case.events.filter(action__in=KINDS).order_by("sequence"):
                updates.append({
                    "case_ref": case.public_ref, "sequence": event.sequence,
                    "kind": event.action, "label": KINDS[event.action],
                    "evidence_version": event.evidence_version,
                    "answer_revision": event.answer_revision,
                    "occurred_at": event.created_at, "seen": event.pk in seen,
                    # Historical alerts remain history, not claims of current readiness.
                    "historical": event.sequence != case.revision,
                })
    return sorted(updates, key=lambda row: (row["occurred_at"], row["case_ref"], row["sequence"]),
                  reverse=True)


def mark_seen(*, case_id, sequence, subject_id, provider, synthetic_fixtures_only=False):
    if type(sequence) is not int or not 1 <= sequence <= casework.MAX_HISTORY:
        raise casework.CaseConflict("invalid_update_sequence")
    with casework._staff_case(case_id, subject_id, provider,
                             synthetic_fixtures_only) as (case, identity):
        event = case.events.filter(sequence=sequence, action__in=KINDS).first()
        if event is None:
            raise casework.CaseConflict("update_unavailable")
        _, created = SeenUpdate.objects.get_or_create(
            event=event, provider_id=provider.provider_id, subject_id=identity.subject_id,
            defaults={"auth_epoch": identity.auth_epoch},
        )
        return created
