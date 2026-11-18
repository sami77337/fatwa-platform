"""Private RTL human review forms; existing authenticated case identities only."""

import json

from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from apps.casework import services as cases
from apps.casework_web.access import RequestDirectory, current_staff
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer, _provider
from apps.intake_workflow.guards import SyntheticWriteDenied
from apps.mufti_review.identity import IdentityUnavailable

from . import review
from .evaluation import load_fixture


def proposed_bundle():
    data, _ = load_fixture()
    return {
        **{k: data[k] for k in ("synthetic_only", "clock", "records")},
        "queries": [{k: v for k, v in q.items() if k != "review_status"} for q in data["queries"]],
    }


@csrf_protect
@sensitive_post_parameters()
def desk(request):
    try:
        ref = request.POST.get("case_ref", "")
        directory = _provider()
        actor = current_staff(request, directory, case_key=ref)
        provider = RequestDirectory(
            directory, actor, authenticated_provider_id=directory.provider_id
        )
        common = dict(subject_id=actor.subject_id, provider=provider, synthetic_fixtures_only=True)
        case = next((c for c in cases.list_cases(**common) if c["public_ref"] == ref), None)
        if case is None:
            raise cases.CaseConflict("evaluation_case_unavailable")
        common["case_id"] = case["case_id"]
        result = review.history(**common)
        if request.method == "POST":
            action = request.POST.get("action", "").removeprefix("research_evaluation_")
            if action == "open":
                _form(request, {"action", "case_ref"})
            elif action == "propose":
                fields = _form(request, {"action", "case_ref", "expected_number", "bundle", "note"})
                if len(fields["bundle"]) > 150000:
                    raise InvalidForm("evaluation_bundle_too_large")
                review.propose(
                    **common,
                    expected_number=0
                    if fields["expected_number"] == "0"
                    else _integer(fields["expected_number"]),
                    bundle=json.loads(fields["bundle"]),
                    note=fields["note"],
                )
            elif action in {"APPROVE", "REJECT"}:
                row = result["versions"][0] if result["versions"] else None
                if row is None:
                    raise InvalidForm("evaluation_missing")
                keys = {
                    "action",
                    "case_ref",
                    "revision_id",
                    "corpus_sha256",
                    "judgements_sha256",
                    "note",
                    "confirm",
                }
                keys |= {
                    f"r_{i}_{k}" for i in range(len(row["judgements"])) for k in ("verdict", "note")
                }
                fields = _form(request, keys)
                reviews = [
                    {
                        "id": q["id"],
                        "verdict": fields[f"r_{i}_verdict"],
                        "note": fields[f"r_{i}_note"],
                    }
                    for i, q in enumerate(row["judgements"])
                ]
                review.decide(
                    **common,
                    revision_id=fields["revision_id"],
                    corpus_sha256=fields["corpus_sha256"],
                    judgements_sha256=fields["judgements_sha256"],
                    action=action,
                    confirmed=fields["confirm"] == "yes",
                    reviews=reviews,
                    note=fields["note"],
                )
            else:
                raise InvalidForm("evaluation_action_invalid")
            result = review.history(**common)
        else:
            return private(HttpResponse(status=405))
        current = result["versions"][0] if result["versions"] else None
        bundle = (
            {**current["corpus"], "queries": current["judgements"]}
            if current
            else proposed_bundle()
        )
        return private(
            render(
                request,
                "arabic_search_eval/review.html",
                {
                    "result": result,
                    "current": current,
                    "bundle": json.dumps(bundle, ensure_ascii=False, indent=2),
                },
            )
        )
    except IdentityUnavailable:
        return private(HttpResponse("يلزم دخول مخول للقضية.", status=403))
    except (InvalidForm, json.JSONDecodeError, TypeError):
        return private(HttpResponse("نموذج المراجعة غير صالح؛ لم يسجل قرار.", status=400))
    except cases.CaseConflict:
        return private(HttpResponse("المراجعة أو إصدارها أو صلاحيتها غير متاحة.", status=409))
    except (DatabaseError, SyntheticWriteDenied):
        return private(HttpResponse("المراجعة غير متاحة الآن.", status=503))
