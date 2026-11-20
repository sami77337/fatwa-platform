"""Real nonempty index seed and fresh-process verification with no restored grants."""

import uuid
from contextlib import contextmanager
from dataclasses import replace

from django.db import IntegrityError, transaction
from django.test import override_settings

from apps.casework import services as cases
from apps.casework.models import Case
from apps.experimental_publication.tests import Directory
from apps.mufti_review.identity import IdentityUnavailable
from apps.research_library.test_support import bind_identity_snapshot
from apps.research_workspace.tests import SyntheticRights
from apps.source_rights import services as rights
from apps.source_rights.tests import Authority as RightsAuthority
from apps.transcript_case_links import services as transcripts
from apps.transcript_case_links.tests import bundle

from . import services
from .models import SearchDocument, SearchGeneration
from .test_support import FixtureAuthority, KnowledgeAuthority

TABLES = ("canonical_search_searchgeneration", "canonical_search_searchdocument")
FUNCTIONS = (
    "cs_immutable",
    "cs_generation_insert",
    "cs_document_insert",
    "cs_generation_complete",
    "cs_unique_sources",
)
TRIGGERS = (
    "cs_generation_insert",
    "cs_generation_immutable",
    "cs_document_insert",
    "cs_document_immutable",
    "cs_generation_complete",
    "cs_generation_unique_sources",
)


@contextmanager
def configuration(pins):
    directory = bind_identity_snapshot(Directory([pins["public_ref"]]))
    with override_settings(
        FATWA_CANONICAL_SEARCH_ENABLED=True,
        FATWA_CANONICAL_SEARCH_AUTHORITY=FixtureAuthority(pins["public_ref"]),
        FATWA_CASEWORK_IDENTITY_PROVIDER=directory,
        FATWA_RESEARCH_WORKSPACE_ENABLED=True,
        FATWA_KNOWLEDGE_LINKS_ENABLED=True,
        FATWA_RESEARCH_WORKSPACE_RIGHTS=SyntheticRights(pins["public_ref"]),
        FATWA_KNOWLEDGE_LINKS_AUTHORITY=KnowledgeAuthority(pins["public_ref"]),
        FATWA_SOURCE_RIGHTS_ENFORCED=True,
        FATWA_SOURCE_RIGHTS_ENABLED=True,
        FATWA_SOURCE_RIGHTS_AUTHORITY=RightsAuthority(pins["public_ref"]),
    ):
        yield dict(
            case_id=pins["case_id"],
            subject_id="editor",
            provider=directory,
            synthetic_fixtures_only=True,
        )


def populate():
    key = "canonical-search-recovery-" + uuid.uuid4().hex
    receipt = cases.intake_case(
        original_question="سُؤالٌ اصطناعيّ عن المُعاملات المالية للاستعادة فقط",
        source_event_id=key,
        requester_id=key,
        idempotency_key=key,
        synthetic_fixtures_only=True,
    )
    pins = {name: str(receipt[name]) for name in ("case_id", "public_ref")}
    with configuration(pins) as base:
        preview = transcripts.preview(**base, bundle=bundle())
        link = transcripts.attach(
            **base, upload_id=preview["upload_id"], external_id=preview["entries"][0].external_id
        )
        source = rights.register(**base, kind="PRIVATE_TRANSCRIPT", target_id=link["link_id"])
        grant = rights.propose(
            **base,
            source_id=source["id"],
            expected_number=0,
            uses=["READ"],
            basis="Synthetic source created for the recovery drill",
            note="Explicit private text read only",
            ttl_minutes=120,
        )
        rights.review(
            **{**base, "subject_id": "publisher"},
            revision_id=grant["id"],
            action="APPROVE",
            confirmed=True,
            note="Independent synthetic source review",
        )
        case = Case.objects.get(pk=pins["case_id"])
        built = services.rebuild(
            **base,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_generation=0,
            request_key=uuid.uuid4(),
        )
        generation = SearchGeneration.objects.get(pk=built["generation_id"])
        pins.update(
            generation_id=str(generation.pk),
            generation_digest=generation.digest,
            document_digests=list(
                generation.documents.order_by("ordinal").values_list("digest", flat=True)
            ),
        )
        assert len(pins["document_digests"]) == 3
    return pins


def verify_restored(pins):
    denials = {}
    with configuration(pins) as base:
        generation = SearchGeneration.objects.get(pk=pins["generation_id"])
        assert generation.digest == pins["generation_digest"]
        assert (
            list(generation.documents.order_by("ordinal").values_list("digest", flat=True))
            == pins["document_digests"]
        )
        found = services.search(**base, value="المعاملات", mode="FTS")
        assert found["total"] == 1
        selected = found["results"][0]
        opened = services.open_source(
            **base, generation_id=selected["generation_id"], document_id=selected["document_id"]
        )
        assert "المُعاملات" in opened["text"]
        assert services.search(**base, value="المعاملاتت", mode="FUZZY")["total"] == 1
        assert services.search(**base, value="لاختبار حفظ النص", kind="TRANSCRIPT")["total"] == 1
        for model in (SearchGeneration, SearchDocument):
            try:
                with transaction.atomic():
                    model.objects.filter(
                        pk__in=model.objects.filter(
                            **(
                                {"case_id": pins["case_id"]}
                                if model is SearchGeneration
                                else {"generation_id": pins["generation_id"]}
                            )
                        ).values_list("pk", flat=True)
                    ).update(digest="0" * 64)
                raise AssertionError("Restored search index accepted mutation")
            except IntegrityError:
                pass
        with override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=None):
            try:
                services.search(**base, value="المعاملات")
                raise AssertionError("Restore fabricated a search authority")
            except cases.CaseConflict:
                denials["missing_authority"] = True
        editor = base["provider"].identities["editor"]
        base["provider"].identities["editor"] = replace(editor, active=False)
        try:
            services.search(**base, value="المعاملات")
            raise AssertionError("Restore fabricated a current staff identity")
        except (cases.CaseConflict, IdentityUnavailable):
            denials["inactive_identity"] = True
        finally:
            base["provider"].identities["editor"] = editor
        assert services.search(**base, value="المعاملات", mode="FTS")["total"] == 1
    return {
        "tables": TABLES,
        "generation_digest": pins["generation_digest"],
        "verified_documents": len(pins["document_digests"]),
        "fts_and_fuzzy_after_restore": True,
        "denials": denials,
        "denial_checks": {key: 1 for key in denials},
        "denied_read_count": len(denials),
        "positive_reads_after_denial": True,
    }
