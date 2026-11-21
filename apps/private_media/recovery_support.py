"""Read-only current-session protocol proof over actually restored private bytes.

The feature owns no durable table. Source rows/blobs are covered by the existing
library recovery inventory. No ticket, session, key or permission is serialized
into recovery pins; fresh synthetic trust is explicitly supplied after restore.
"""

from dataclasses import replace
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.test import RequestFactory, override_settings
from django.urls import resolve
from django.utils import timezone

from apps.casework_web import access
from apps.mufti_review.identity import validate_identity
from apps.research_library import recovery_support as library_recovery
from apps.research_library.test_support import video

from . import links
from .test_signed_links import LINK_SETTINGS

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()
DENIAL_CHECKS = {
    "unsigned_private_url": 2,
    "same_actor_different_browser": 2,
    "missing_signing_key": 2,
    "rotated_link_epoch": 2,
    "missing_current_identity": 2,
    "revoked_current_identity": 2,
    "revoked_current_read": 2,
    "revoked_current_download": 2,
    "cross_purpose_ticket": 2,
}


def populate():
    return library_recovery.populate()


def _session(directory):
    """Use actual credential authentication and the application's signed cookie.

    RequestFactory skips only HTTP throttling writes so recovery verification stays
    read-only. Current session verification and every domain boundary still run.
    Native login/navigation/downloads are proved separately by browser journeys.
    """
    request = RequestFactory().get(
        "/casework/staff/", REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1"
    )
    actor = directory.authenticate("synthetic-editor-credential-32-characters")
    validate_identity(actor)
    get_token(request)
    response = access.set_staff_cookie(request, HttpResponse(), directory, actor)
    request.COOKIES[access.COOKIE] = response.cookies[access.COOKIE].value
    # The current verifier must accept this exact fresh authenticated browser.
    current = access.current_staff(request, directory)
    if (
        replace(current, valid_until=actor.valid_until) != actor
        or not timezone.now() < current.valid_until <= actor.valid_until
    ):
        raise AssertionError("Restored current staff session was not verified")
    return request


def _read(session, url, method="GET"):
    request = getattr(RequestFactory(), method.lower())(
        url, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1", HTTP_RANGE="bytes=4-19"
    )
    request.COOKIES = session.COOKIES.copy()
    request.META["CSRF_COOKIE"] = session.META["CSRF_COOKIE"]
    match = resolve(urlsplit(url).path)
    return match.func(request, *match.args, **match.kwargs)


def verify_restored(pins):
    connection.close()
    receipt = pins["case"]
    before = library_recovery._row_pins(receipt["case_id"])
    if (
        before != pins["tables"]
        or library_recovery._canonical(receipt["case_id"]) != receipt["canonical_sha256"]
    ):
        raise AssertionError("Restored private media sources changed")
    denied = {}

    with library_recovery._fixture(receipt) as common, override_settings(**LINK_SETTINGS):
        session = _session(common["provider"])
        other_session = _session(common["provider"])
        book_id = pins["versions"]["book"]["version_id"]
        path = f"/casework/staff/library/{book_id}/file/"
        download_path = f"/casework/staff/library/{book_id}/download/"
        inline = links.issue(session, path)
        download = links.issue(session, download_path, purpose="DOWNLOAD")

        def available():
            # Both retained private book and released video still use their private
            # domain reader here; public release is not borrowed as a permission.
            for label, raw in (("book", library_recovery.BOOK_BYTES), ("video", video())):
                version_id = pins["versions"][label]["version_id"]
                target = links.issue(session, f"/casework/staff/library/{version_id}/file/")
                response = _read(session, target)
                if response.status_code != 206 or response.content != raw[4:20]:
                    raise AssertionError("Restored signed range did not read the exact original")
                response = _read(session, target, "HEAD")
                if (
                    response.status_code != 200
                    or response.content
                    or int(response["Content-Length"]) != len(raw)
                ):
                    raise AssertionError("Restored signed HEAD did not validate the exact original")

        def refuse(label, target=inline, browser=session):
            count = 0
            for method in ("GET", "HEAD"):
                response = _read(browser, target, method)
                if response.status_code != 404 or response.get("Referrer-Policy") != "no-referrer":
                    raise AssertionError("Restored signed reader ignored " + label)
                if any(
                    name in response
                    for name in ("Content-Disposition", "Content-Range", "ETag", "X-Content-SHA256")
                ):
                    raise AssertionError("Restored refusal exposed source metadata")
                count += 1
            denied[label] = count

        available()
        # Prove the new browser is currently authorized before rejecting the URL
        # bound to the first one. This is not an anonymous-only denial test.
        other_url = links.issue(other_session, path)
        if _read(other_session, other_url).status_code != 206:
            raise AssertionError("Independent restored browser was not authorized")
        refuse("unsigned_private_url", path)
        refuse("same_actor_different_browser", browser=other_session)
        with override_settings(FATWA_PRIVATE_MEDIA_LINKS_KEY=None):
            refuse("missing_signing_key")
        with override_settings(FATWA_PRIVATE_MEDIA_LINKS_EPOCH="synthetic-restored-rotated"):
            refuse("rotated_link_epoch")
        with override_settings(FATWA_CASEWORK_IDENTITY_PROVIDER=None):
            refuse("missing_current_identity")
        directory = common["provider"]
        actor = directory.identities["editor"]
        directory.identities["editor"] = replace(actor, active=False)
        try:
            refuse("revoked_current_identity")
        finally:
            directory.identities["editor"] = actor
        authority = settings.FATWA_RESEARCH_LIBRARY_AUTHORITY
        for action, label, target in (
            ("READ", "revoked_current_read", inline),
            ("DOWNLOAD", "revoked_current_download", download),
        ):
            authority.denied.add(action)
            try:
                refuse(label, target)
            finally:
                authority.denied.remove(action)
        refuse("cross_purpose_ticket", inline.replace("/file/", "/download/"))
        available()

    if denied != DENIAL_CHECKS:
        raise AssertionError("Restored signed-link denial coverage changed")
    if (
        library_recovery._row_pins(receipt["case_id"]) != before
        or library_recovery._canonical(receipt["case_id"]) != receipt["canonical_sha256"]
    ):
        raise AssertionError("Signed-link recovery reader changed source or history")
    return {
        "status": "PASS",
        "new_table_count": 0,
        "denial_checks": denied,
        "denied_read_count": sum(denied.values()),
        "positive_reads_after_denial": True,
        "fresh_connection": True,
        "exact_restored_private_originals": True,
        "current_browser_sessions_required": True,
        "canonical_and_history_unchanged": True,
        "serialized_session_or_link_grants": False,
    }
