"""Opt-in case-scoped title search over the current authorized registered corpus."""

from django.conf import settings

from apps.case_citations import services as citations
from apps.casework import services as cases
from apps.delivery_queue import services as queue
from apps.platform_recovery.integration import mutation_service
from apps.research_workspace import reference_batch
from apps.research_workspace import services as workspace
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
    page=1,
    page_size=20,
    synthetic_fixtures_only=False,
):
    """All current registered TOC candidates (max 64), then authorized pagination.

    Counts/facets cover matches in this case/edition, never the global corpus.
    Fresh rights/provenance/policy are checked again before any aggregates leave.
    """
    workspace._enabled()
    if getattr(settings, "FATWA_ARABIC_SEARCH_EVAL_ENABLED", False) is not True or not required():
        raise cases.CaseConflict("arabic_search_eval_disabled")
    try:
        query_tokens(query)
    except ValueError as exc:
        raise cases.CaseConflict("research_query_invalid") from exc
    if (
        type(edition_id) is not int
        or edition_id < 1
        or type(page) is not int
        or not 1 <= page <= 64
        or type(page_size) is not int
        or not 1 <= page_size <= 20
        or type(printed_part) is not str
        or len(printed_part) > 100
        or any(ord(c) < 32 for c in printed_part)
        or (
            printed_page is not None
            and (type(printed_page) is not int or not 1 <= printed_page <= 999999999)
        )
    ):
        raise cases.CaseConflict("research_query_invalid")
    with (
        queue.synthetic_queue_atomic(),
        cases._staff_case(case_id, subject_id, provider, synthetic_fixtures_only) as (case, actor),
        citations._projection_expiry_guard(),
        reference_batch.policy_boundary(),
    ):
        batch_args = dict(case=case, actor=actor, provider=provider, edition_id=edition_id)
        authorized = reference_batch.read_locked(**batch_args)
        rows = [
            row
            for row in authorized
            if (not printed_part or row["source"]["printed_part"] == printed_part)
            and (printed_page is None or row["source"]["printed_page"] == printed_page)
        ]
        hits = rank_titles(
            query,
            [Candidate(row["resource"]["identifier"], row["title"]) for row in rows],
            limit=64,
        )
        reference_batch.recheck_locked(expected=authorized, **batch_args)
        by_id = {row["resource"]["identifier"]: row for row in rows}
        selected = []
        for hit in hits[(page - 1) * page_size : page * page_size]:
            row = by_id[hit.identifier]
            selected.append(
                {
                    **{k: v for k, v in row.items() if not k.startswith("_")},
                    "ranking": {"tier": hit.tier, "reason": hit.reason},
                }
            )
        facets = {}
        for hit in hits:
            part = by_id[hit.identifier]["source"]["printed_part"]
            facets[part] = facets.get(part, 0) + 1
        workspace._recheck(case, actor, provider)
        return {
            "public_ref": case.public_ref,
            "revision": case.revision,
            "evidence_version": case.evidence_version,
            "results": selected,
            "ranking_version": VERSION,
            "coverage": "CURRENT_CASE_REGISTERED_TOC",
            "candidate_pool_limit": 64,
            "total": len(hits),
            "page": page,
            "page_size": page_size,
            "pages": (len(hits) + page_size - 1) // page_size,
            "next_page": page + 1 if page * page_size < len(hits) else None,
            "previous_page": page - 1 if page > 1 else None,
            "facets": [
                {"printed_part": part, "count": count} for part, count in sorted(facets.items())
            ],
            "human_review": "PENDING",
            "material": "TOC_METADATA_ONLY",
        }
