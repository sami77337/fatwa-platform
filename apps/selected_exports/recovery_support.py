"""Synthetic nonempty recovery fixture; never reconstructs real identity or rights."""

import uuid

from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.case_citations import services as citations
from apps.case_citations.tests import source_fixture
from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.reference.models import ReferenceHeading
from apps.research_workspace import services as research
from apps.research_workspace.source_rights_adapter import SourceRightsAdapter
from apps.source_rights import services as ledger
from apps.source_rights.tests import Authority as SourceAuthority

from . import services
from .models import ExportArtifact, ExportEvent, ExportJob
from .tests import FixtureExportAuthority

TABLES = (
    "selected_exports_exportjob",
    "selected_exports_exportevent",
    "selected_exports_exportartifact",
)
TRIGGERS = (
    "selected_export_job_guard",
    "selected_export_event_guard",
    "selected_export_artifact_guard",
)


def _configuration(pins):
    directory = Directory([pins["public_ref"]])
    common = dict(
        case_id=pins["case_id"],
        subject_id="editor",
        provider=directory,
        synthetic_fixtures_only=True,
    )
    configuration = override_settings(
        FATWA_SELECTED_EXPORTS_ENABLED=True,
        FATWA_SELECTED_EXPORTS_AUTHORITY=FixtureExportAuthority(pins["public_ref"]),
        FATWA_RESEARCH_WORKSPACE_ENABLED=True,
        FATWA_RESEARCH_WORKSPACE_RIGHTS=SourceRightsAdapter(),
        FATWA_CASE_CITATIONS_ENABLED=True,
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_SOURCE_RIGHTS_ENABLED=True,
        FATWA_SOURCE_RIGHTS_ENFORCED=True,
        FATWA_SOURCE_RIGHTS_AUTHORITY=SourceAuthority(pins["public_ref"]),
    )
    return common, configuration


def populate():
    key = "selected-export-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="سؤال استعادة اصطناعي مستقل لا يدخل التصدير",
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    pins = {name: str(receipt[name]) for name in ("case_id", "public_ref")}
    common, configuration = _configuration(pins)
    with configuration:
        edition = source_fixture()
        heading = ReferenceHeading.objects.get(edition_id=edition, source_row_id=2)
        registered = ledger.register(**common, kind="TOC_METADATA", target_id=heading.pk)
        proposed = ledger.propose(
            **common,
            source_id=registered["id"],
            expected_number=0,
            uses=["READ"],
            basis="Synthetic recovery rights evidence",
            note="Independent export source review",
            ttl_minutes=60,
        )
        ledger.review(
            **{**common, "subject_id": "publisher"},
            revision_id=proposed["id"],
            action="APPROVE",
            confirmed=True,
            note="Synthetic independent review",
        )
        opened = citations.read_source(**common, edition_id=edition, source_row_id=2)
        selected = research._source_resource(opened["source"], opened["source_sha256"])
        job = services.prepare(
            **common,
            selected=[selected],
            format="JSONL",
            include_files=False,
            request_key=uuid.uuid4(),
            expected_revision=1,
            expected_evidence_version=1,
        )
        services.command(
            **common,
            job_id=job["id"],
            action="QUEUE",
            request_key=uuid.uuid4(),
            expected_revision=job["revision"],
        )
        result = services.run_job(**common, job_id=job["id"], request_key=uuid.uuid4())
        assert result["state"] == "READY"
        download_request = uuid.uuid4()
        downloaded = services.download(**common, job_id=job["id"], request_key=download_request)
        pins.update(job_id=job["id"], sha256=downloaded["sha256"], download_request=str(download_request))
        assert all(model.objects.exists() for model in (ExportJob, ExportEvent, ExportArtifact))
    return pins


def verify_restored(pins):
    common, configuration = _configuration(pins)
    with configuration:
        # A replay rechecks current rights and exact bytes without appending a
        # new DOWNLOAD audit to the restored snapshot being compared by the drill.
        result = services.download(**common, job_id=pins["job_id"], request_key=pins["download_request"])
        assert result["sha256"] == pins["sha256"]
        assert services.status(**common, job_id=pins["job_id"])["state"] == "READY"
        try:
            with transaction.atomic():
                ExportArtifact.objects.filter(job_id=pins["job_id"]).update(raw=b"changed")
            raise AssertionError("Restored export artifact must remain immutable")
        except IntegrityError:
            pass
        with override_settings(FATWA_SELECTED_EXPORTS_AUTHORITY=None):
            try:
                services.download(**common, job_id=pins["job_id"], request_key=pins["download_request"])
                raise AssertionError("Restoration must not fabricate export authority")
            except cases.CaseConflict:
                pass
        common["provider"].identities.pop("editor")
        try:
            services.status(**common, job_id=pins["job_id"])
            raise AssertionError("Restoration must not fabricate identity authority")
        except cases.CaseConflict:
            pass
    return {"tables": TABLES, "artifact_sha256": pins["sha256"], "current_authority_required": True}
