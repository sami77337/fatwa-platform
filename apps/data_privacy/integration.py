"""Small lazy hooks for existing readers; no route, query or identity rewriting."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.apps import apps

READERS = ContextVar("privacy_current_source_readers", default=())
SOURCE_USES = ContextVar("privacy_current_original_uses", default=())
SOURCE_READERS = ContextVar("privacy_current_original_publishers", default=())


@contextmanager
def projection(*, atomic=True):
    from .services import projection as boundary

    with boundary(atomic=atomic) as guard:
        yield guard


def projected(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with projection():
            return function(*args, **kwargs)

    return wrapped


def contextual(function):
    @wraps(function)
    @contextmanager
    def wrapped(*args, **kwargs):
        with projection():
            with function(*args, **kwargs) as value:
                yield value

    return wrapped


def public_contextual(function):
    @wraps(function)
    @contextmanager
    def wrapped(*args, **kwargs):
        from apps.library_preview.services import PreviewUnavailable

        from .services import PrivacyDenied

        try:
            with projection():
                with function(*args, **kwargs) as value:
                    yield value
        except PrivacyDenied as exc:
            raise PreviewUnavailable() from exc

    return wrapped


def public_projected(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from apps.library_preview.services import PreviewUnavailable

        from .services import PrivacyDenied

        try:
            with projection():
                return function(*args, **kwargs)
        except PrivacyDenied as exc:
            raise PreviewUnavailable() from exc

    return wrapped


@contextmanager
def using(principal):
    token = READERS.set((*READERS.get(), principal))
    try:
        yield
    finally:
        READERS.reset(token)


@contextmanager
def published_sources(principal):
    """A public copy consumes originals only through its current real publisher."""
    token = SOURCE_USES.set((*SOURCE_USES.get(), "PUBLISH"))
    reader = SOURCE_READERS.set((*SOURCE_READERS.get(), principal))
    try:
        with using(principal):
            yield
    finally:
        SOURCE_READERS.reset(reader)
        SOURCE_USES.reset(token)


def original_action(action="READ"):
    return SOURCE_USES.get()[-1] if SOURCE_USES.get() else action


def source(kind, identifier, *, action="READ"):
    if SOURCE_READERS.get():
        from . import services

        if not services.applicable(kind, str(identifier)):
            return None
        principal = SOURCE_READERS.get()[-1]
        if principal is None:
            raise services.PrivacyDenied("privacy_current_publisher_required")
        return services.require(
            kind, identifier, principal=principal, action=original_action(action)
        )
    return current(kind, identifier, action=original_action(action))


def original(kind, identifier, *, provider, actor, action="READ"):
    """Keep the publisher distinct from a nested source's native scholarly actor."""
    if SOURCE_READERS.get():
        return source(kind, identifier, action=action)
    return staff(kind, identifier, provider=provider, actor=actor, action=action)


def current(kind, identifier, *, action="READ"):
    from . import services

    if not services.applicable(kind, str(identifier)):
        return None
    principal = next((value for value in reversed(READERS.get()) if value is not None), None)
    if principal is None:
        raise services.PrivacyDenied("privacy_current_reader_required")
    return services.require(kind, identifier, principal=principal, action=action)


def allowed(kind, identifier, *, action="READ"):
    from .services import PrivacyDenied

    try:
        current(kind, identifier, action=action)
        return True
    except PrivacyDenied:
        return False


def staff(kind, identifier, *, provider, actor, action="READ"):
    from . import services

    if not services.applicable(kind, str(identifier)):
        return None
    return services.require(
        kind, identifier, principal=services.staff_principal(provider, actor), action=action
    )


def public(kind, identifier, *, action="READ"):
    from . import services

    if not services.applicable(kind, str(identifier)):
        return None
    return services.require(kind, identifier, principal=services.public_principal(), action=action)


def evidence_allowed(evidence, *, action="READ"):
    """A copied attachment label or transcript question keeps its source gate."""
    for kind, label in (
        ("ATTACHMENT", "case_attachments.CaseAttachment"),
        ("TRANSCRIPT_LINK", "transcript_case_links.TranscriptLink"),
        ("SOURCE_RECEIPT", "source_case_intake.EvidenceBinding"),
    ):
        app_label = label.split(".")[0]
        if not apps.is_installed("apps." + app_label):
            continue
        model = apps.get_model(label)
        source_ids = model.objects.filter(evidence_id=evidence.pk).values_list("pk", flat=True)
        if any(not allowed(kind, identifier, action=action) for identifier in source_ids):
            return False
    return True


def _original(case):
    if apps.is_installed("apps.source_case_intake"):
        model = apps.get_model("source_case_intake.EvidenceBinding")
        for identifier in model.objects.filter(case=case, evidence__version=1).values_list(
            "pk", flat=True
        ):
            source("SOURCE_RECEIPT", identifier)


@contextmanager
def staff_case(case, actor, provider):
    from . import services

    with projection():
        principal = (
            services.staff_principal(provider, actor)
            if services.applicable("CASE", str(case.pk))
            else None
        )
        with using(principal):
            source("CASE", case.pk)
            _original(case)
            yield


@contextmanager
def requester_case(case, token_digest):
    from . import services

    with projection():
        principal = (
            services.requester_principal(case, token_digest)
            if services.applicable("CASE", str(case.pk))
            else None
        )
        with using(principal):
            current("CASE", case.pk)
            _original(case)
            yield


class PrivacyResponses:
    """Final pure projection across native rendering, without late provider calls."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from apps.casework_web.guard import denied
        from apps.staff_sessions.integration import retain_final_guard

        from .services import PrivacyDenied

        try:
            # Retain final response pins without holding a database transaction
            # around authentication or an external candidate provider.
            with projection(atomic=False) as guard:
                retain_final_guard(
                    guard.final_pins, failure=PrivacyDenied, code="private_projection_unavailable"
                )
                response = self.get_response(request)
                if getattr(response, "streaming", False) and guard.uses:
                    raise PrivacyDenied("privacy_buffered_projection_required")
                return response
        except PrivacyDenied:
            response = denied("private_projection_unavailable", 404)
            response["Referrer-Policy"] = "no-referrer"
            return response
