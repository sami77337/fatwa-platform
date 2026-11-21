"""Map existing closed research resources to exact classified source versions."""

from django.apps import apps

from . import integration, services

DIRECT = {
    "ATTACHMENT": "ATTACHMENT",
    "ANSWER_MEDIA": "ANSWER_PART",
    "TRANSCRIPT": "TRANSCRIPT_LINK",
    "KNOWLEDGE": "KNOWLEDGE_REVISION",
}


def _references(case, *, edition_id, source_row_id=None):
    if not apps.is_installed("apps.source_rights"):
        return []
    model = apps.get_model("source_rights.SourceVersion")
    rows = model.objects.filter(
        sourceregistration__case=case, heading__edition_id=edition_id
    ).distinct()
    if source_row_id is not None:
        rows = rows.filter(heading__source_row_id=source_row_id)
    return list(rows.values_list("pk", flat=True))


def reference(case, source, *, action="READ"):
    pin = source["source"]
    identifiers = _references(
        case, edition_id=pin["edition_id"], source_row_id=pin["source_row_id"]
    )
    if not identifiers and services.enabled():
        raise services.PrivacyDenied("privacy_registered_source_required")
    for identifier in identifiers:
        integration.source("SOURCE_VERSION", identifier, action=action)


def transcript(case, identifier, *, action="READ"):
    integration.source("TRANSCRIPT_LINK", identifier, action=action)
    if apps.is_installed("apps.source_rights"):
        for source_id in (
            apps.get_model("source_rights.SourceVersion")
            .objects.filter(transcript_id=identifier, sourceregistration__case=case)
            .values_list("pk", flat=True)
        ):
            integration.source("SOURCE_VERSION", source_id, action=action)


def permit(case, actor, provider, action, resource):
    """Additional veto only; callers still enforce the exact domain resource pin."""
    if action not in {"READ", "SEARCH", "EXPORT", "PUBLISH", "AI"}:
        raise services.PrivacyDenied("privacy_resource_action_invalid")

    def check(kind, identifier):
        return integration.original(kind, identifier, provider=provider, actor=actor, action=action)

    if resource.kind in DIRECT:
        check(DIRECT[resource.kind], resource.identifier)
        if resource.kind == "TRANSCRIPT" and apps.is_installed("apps.source_rights"):
            for identifier in (
                apps.get_model("source_rights.SourceVersion")
                .objects.filter(transcript_id=resource.identifier, sourceregistration__case=case)
                .values_list("pk", flat=True)
            ):
                check("SOURCE_VERSION", identifier)
        return
    if resource.kind == "REFERENCE":
        try:
            edition, row = (int(value) for value in resource.identifier.split(":"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise services.PrivacyDenied("privacy_resource_identity_invalid") from exc
        identifiers = _references(case, edition_id=edition, source_row_id=row)
        if not identifiers and services.enabled():
            raise services.PrivacyDenied("privacy_registered_source_required")
        for identifier in identifiers:
            check("SOURCE_VERSION", identifier)
        return
    if resource.kind == "EDITION":
        # A public reference catalog is not a private scholarly corpus. Within
        # a case, its selector still needs one admitted registered source; the
        # selector never grants any other heading or private original text.
        identifiers = _references(case, edition_id=resource.edition_id)
        for identifier in identifiers:
            try:
                check("SOURCE_VERSION", identifier)
                return
            except services.PrivacyDenied:
                continue
        if services.enabled() or identifiers:
            raise services.PrivacyDenied("privacy_registered_source_required")
        return
    if services.enabled():
        raise services.PrivacyDenied("privacy_resource_identity_invalid")


def research(case, actor, provider, action, resource):
    permit(
        case,
        actor,
        provider,
        integration.original_action("SEARCH" if action in {"DISCOVER", "SEARCH_TEXT"} else "READ"),
        resource,
    )
