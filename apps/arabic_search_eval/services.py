"""Opt-in composition over the existing case-scoped research search service."""

from django.conf import settings

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.delivery_queue import services as queue
from apps.platform_recovery.integration import mutation_service
from apps.research_workspace import services as workspace
from apps.research_workspace.rights import Resource, require
from apps.source_rights.enforcement import required

from .ranking import VERSION, Candidate, query_tokens, rank_titles


@mutation_service
def search_reference_titles(
    *,
    case_id,
    subject_id,
    provider,
    query,
    edition_id,
    printed_part="",
    printed_page=None,
    synthetic_fixtures_only=False,
):
    """Search a bounded authorized window, preserving exact source/open pins.

    Caller must label the window limit; absence is NOT a corpus-wide no-match.
    Strict source ledger is mandatory even if a legacy workspace policy exists.
    """
    workspace._enabled()
    if getattr(settings, "FATWA_ARABIC_SEARCH_EVAL_ENABLED", False) is not True or not required():
        raise cases.CaseConflict("arabic_search_eval_disabled")
    try:
        query_tokens(query)
    except ValueError as exc:
        raise cases.CaseConflict("research_query_invalid") from exc
    if type(edition_id) is not int or edition_id < 1:
        raise cases.CaseConflict("research_query_invalid")
    common = dict(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    )
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        citations._projection_expiry_guard(),
    ):
        found = workspace.search(
            **common,
            query="",
            kind="REFERENCE",
            edition_id=edition_id,
            printed_part=printed_part,
            printed_page=printed_page,
        )
        rows = found["results"]
        for row in rows:
            workspace.open_resource(**common, resource=Resource(**row["resource"]))
        hits = rank_titles(
            query, [Candidate(row["resource"]["identifier"], row["title"]) for row in rows]
        )
        by_id = {row["resource"]["identifier"]: row for row in rows}
        selected = []
        for hit in hits:
            row = by_id[hit.identifier]
            resource = Resource(**row["resource"])
            require(actor, provider, case, "DISCOVER", resource)
            workspace.open_resource(**common, resource=resource)
            selected.append({**row, "ranking": {"tier": hit.tier, "reason": hit.reason}})
        workspace._recheck(case, actor, provider)
        return {
            "public_ref": found["public_ref"],
            "revision": found["revision"],
            "evidence_version": found["evidence_version"],
            "results": selected,
            "ranking_version": VERSION,
            "coverage": "BOUNDED_CANDIDATE_WINDOW",
            "candidate_pool_limit": 20,
            "human_review": "PENDING",
            "material": "TOC_METADATA_ONLY",
        }
