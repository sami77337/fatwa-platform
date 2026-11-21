"""Actual restored requester video originals and denial reads without new grants."""

from dataclasses import replace
from hashlib import sha256

from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from tests.casework.test_http import Directory

from . import services
from .models import CaseAttachment
from .tests import new_case, staff_common, upload
from .video_fixtures import video

TABLES = (CaseAttachment._meta.db_table,)
TRIGGERS = ("case_attachment_guard",)


def populate():
    receipt = new_case()
    with override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True, FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED=True):
        saved = []
        for revision, extension in enumerate(("webm", "mp4"), 1):
            original = video(extension)
            row = upload(receipt, raw=original, filename="restored." + extension,
                         media_type="video/" + extension, expected_revision=revision)
            saved.append({"id": row["id"], "extension": extension, "sha256": sha256(original).hexdigest(), "size": len(original)})
        rotated = cases.rotate_access(**staff_common(receipt), requester_id=Case.objects.get(pk=receipt["case_id"]).requester_id)
        return {"case_id": receipt["case_id"], "public_ref": receipt["public_ref"],
                "revoked_token": receipt["token"], "token": rotated["token"], "originals": saved,
                "revision": rotated["revision"]}


def verify_restored(fixture):
    directory = Directory()
    directory.grant(fixture["public_ref"])
    common = dict(case_id=fixture["case_id"], subject_id=directory.current.subject_id,
                  provider=directory, synthetic_fixtures_only=True)
    before = list(CaseAttachment.objects.filter(case_id=fixture["case_id"]).order_by("pk").values())
    case_before = list(Case.objects.filter(pk=fixture["case_id"]).values())
    denials = {}
    def denied(kind, reader):
        try:
            reader()
        except cases.CaseConflict:
            denials[kind] = denials.get(kind, 0) + 1
        else:
            raise AssertionError("restored video accepted missing or revoked access")
    with override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=True, FATWA_CASE_ATTACHMENTS_VIDEO_ENABLED=True):
        for entry in fixture["originals"]:
            for actual in (
                services.staff_read(**common, attachment_id=entry["id"]),
                services.requester_read(token=fixture["token"], attachment_id=entry["id"], synthetic_fixtures_only=True),
            ):
                assert actual["kind"] == "video"
                assert actual["sha256"] == entry["sha256"]
                assert actual["size"] == entry["size"]
                assert sha256(actual["raw"]).hexdigest() == entry["sha256"]
            denied("revoked_requester", lambda: services.requester_read(token=fixture["revoked_token"], attachment_id=entry["id"], synthetic_fixtures_only=True))
            prior = directory.current
            directory.current = replace(prior, active=False)
            try:
                denied("revoked_current_reader", lambda: services.staff_read(**common, attachment_id=entry["id"]))
            finally:
                directory.current = prior
            with override_settings(FATWA_CASE_ATTACHMENTS_ENABLED=False):
                denied("disabled_feature", lambda: services.staff_read(**common, attachment_id=entry["id"]))
            assert services.staff_read(**common, attachment_id=entry["id"])["sha256"] == entry["sha256"]
    assert denials == {"revoked_requester": 2, "revoked_current_reader": 2, "disabled_feature": 2}
    assert list(CaseAttachment.objects.filter(case_id=fixture["case_id"]).order_by("pk").values()) == before
    assert list(Case.objects.filter(pk=fixture["case_id"]).values()) == case_before
    return {"status": "PASS", "video_originals": 2, "exact_originals": True,
            "denial_checks": denials, "denied_read_count": sum(denials.values()), "positive_reads_after_denial": True,
            "metadata_and_case_unchanged": True}
