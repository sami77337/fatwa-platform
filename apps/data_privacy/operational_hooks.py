"""Privacy vetoes use the actual operational actor; no synthetic Mufti identity."""

from django.apps import apps

from . import integration, services


def require(guard, kind, identifier, *, action="READ"):
    return integration.staff(
        kind, identifier, provider=guard.provider, actor=guard.actor, action=action
    )


def allowed(guard, kind, identifier, *, action="READ"):
    try:
        require(guard, kind, identifier, action=action)
        return True
    except services.PrivacyDenied:
        return False


def permission(guard, case, action, resource):
    require(guard, "CASE", case.pk, action="SEARCH" if action == "READ_QUEUE" else "READ")
    if action in {"READ_QUEUE", "READ_CASE"} and apps.is_installed("apps.source_case_intake"):
        for identifier in (
            apps.get_model("source_case_intake.EvidenceBinding")
            .objects.filter(case=case, evidence__version=1)
            .values_list("receipt_id", flat=True)
        ):
            require(
                guard,
                "SOURCE_RECEIPT",
                identifier,
                action="SEARCH" if action == "READ_QUEUE" else "READ",
            )
    kind = resource["kind"]
    if kind == "CASE_PUBLICATION_EDITION":
        if action != "WITHDRAW_PUBLICATION_EDITION":
            require(
                guard,
                "PUBLICATION",
                resource["edition_id"],
                action="PUBLISH" if action == "APPROVE_PUBLICATION_EDITION" else "READ",
            )
    elif kind in {"CASE_RECORDING_SOURCE", "CASE_RECORDING_TRANSCRIPT"}:
        require(guard, "ANSWER_PART", resource["part_id"])
        if resource.get("transcript_id") and action != "WITHDRAW_RECORDING_TRANSCRIPT":
            require(guard, "RECORDING_TRANSCRIPT", resource["transcript_id"])
    elif kind in {"CASE_LESSON_VERSION", "CASE_LESSON_LINK"}:
        require(guard, "CASE", resource["target_case_id"])
        require(guard, "LESSON_VERSION", resource["version_id"])
        version = apps.get_model("scholarly_links.LessonVersion").objects.get(
            pk=resource["version_id"]
        )
        require(guard, "SERIES_VERSION", version.series_version_id)
        if version.source_part_id:
            require(guard, "ANSWER_PART", version.source_part_id)
