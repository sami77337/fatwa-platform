"""Bounded native multi-reference scratch state, signed and bound to this browser.

The state is carried only in POST bodies, never persisted as another answer.
Draft text remains an explicit form value and every final save creates one
canonical answer revision through the existing transaction service.
"""

from django.core import signing
from django.middleware.csrf import get_token
from django.shortcuts import render

from apps.casework import services as cases
from apps.casework_web.guard import private
from apps.casework_web.views import InvalidForm, _form, _integer
from apps.editorial_workbench.reviewer_access import browser_proof

from . import services

SALT = "case-citations.compose.v2"
FIELDS = {
    "action",
    "case_ref",
    "workspace",
    "text",
    "query",
    "edition_id",
    "part",
    "page",
    "editorial_note",
    "command",
}


def _binding(request, actor, provider, case_ref):
    return browser_proof(
        request,
        SALT,
        "|".join([provider.provider_id, actor.subject_id, actor.auth_epoch, case_ref]),
    )


def _read(request, actor, provider, case_ref):
    raw = request.POST.get("workspace", "")
    if len(raw) > 60000:
        raise InvalidForm("citation_workspace_too_large")
    try:
        state = signing.loads(raw, salt=SALT, max_age=1800)
        if (
            set(state)
            != {
                "binding",
                "revision",
                "evidence_version",
                "selections",
                "suggestions",
                "correcting",
            }
            or state["binding"] != _binding(request, actor, provider, case_ref)
            or type(state["selections"]) is not list
            or len(state["selections"]) > services.MAX_CITATIONS
        ):
            raise ValueError("invalid_state")
        cases._mutation_versions(state["revision"], state["evidence_version"])
        return state
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise InvalidForm("citation_workspace_invalid_or_expired") from exc


def _selection(link):
    source = link["source"]
    return dict(
        edition_id=source["edition_id"],
        source_row_id=source["source_row_id"],
        source_sha256=link["source_sha256"],
        editorial_note=link["editorial_note"],
        citation_id=link["id"],
    )


def _page(
    request,
    common,
    selected,
    state,
    *,
    text,
    query="",
    edition_id=None,
    part="",
    page=None,
    editorial_note="",
    message="",
    status=200,
    opened=None,
    history=None,
):
    chosen = []
    for index, item in enumerate(state["selections"]):
        source = services.read_source(
            **common, edition_id=item["edition_id"], source_row_id=item["source_row_id"]
        )
        if source["source_sha256"] != item["source_sha256"]:
            raise cases.CaseConflict("citation_source_changed")
        chosen.append(
            dict(
                source,
                index=index,
                editorial_note=item["editorial_note"],
                citation_id=item.get("citation_id"),
                correction_reason=item.get("correction_reason", ""),
            )
        )
    found = services.search_sources(
        **common, query=query, edition_id=edition_id, printed_part=part, printed_page=page
    )
    get_token(request)
    return private(
        render(
            request,
            "case_citations/composer.html",
            dict(
                selected=selected,
                workspace=signing.dumps(state, salt=SALT, compress=True),
                base_revision=state["revision"],
                base_evidence_version=state["evidence_version"],
                chosen=chosen,
                sources=found,
                text=text,
                query=query,
                edition_id=edition_id,
                part=part,
                page=page,
                editorial_note=editorial_note,
                message=message,
                capacity=len(chosen) >= services.MAX_CITATIONS,
                opened=opened,
                history=history,
                suggestions=state["suggestions"],
                correcting=state["correcting"] is not None,
            ),
            status=status,
        )
    )


def start(request, common, actor, provider):
    services._enabled()
    with cases._staff_case(common["case_id"], common["subject_id"], common["provider"], True) as (
        case,
        _,
    ):
        selected = cases._staff(case)
        answer = case.answers.order_by("-revision").first()
        links = services.citations_for_locked_answer(answer) if answer else []
        state = dict(
            binding=_binding(request, actor, provider, case.public_ref),
            revision=case.revision,
            evidence_version=case.evidence_version,
            selections=[_selection(link) for link in links],
            suggestions=[],
            correcting=None,
        )
        text = answer.text if answer else ""
    return _page(request, common, selected, state, text=text)


def compose(request, common, selected, actor, provider):
    required = FIELDS | ({"confirm"} if "confirm" in request.POST else set())
    fields = _form(request, required)
    state = _read(request, actor, provider, selected["public_ref"])
    cases._text(fields["text"], optional=True)
    cases._text(fields["editorial_note"], optional=True)
    if len(fields["editorial_note"]) > 2000:
        raise InvalidForm("citation_note_too_long")
    edition_id = _integer(fields["edition_id"]) if fields["edition_id"] else None
    page = _integer(fields["page"]) if fields["page"] else None
    # Validate every submitted navigation value before a possible durable save.
    services.search_sources(
        **common,
        query=fields["query"],
        edition_id=edition_id,
        printed_part=fields["part"],
        printed_page=page,
    )
    if "confirm" in fields and fields["confirm"] != "yes":
        raise InvalidForm("human_citation_review_required")
    command = fields["command"]
    message, status = "", 200
    opened, history = None, None
    if command.startswith("open:"):
        values = command.split(":")
        if len(values) != 3:
            raise InvalidForm("citation_command_invalid")
        opened = services.read_source(
            **common, edition_id=_integer(values[1]), source_row_id=_integer(values[2])
        )
    elif command == "suggest":
        state["suggestions"] = services.suggest_sources(
            **common,
            query=fields["query"],
            edition_id=edition_id,
            printed_part=fields["part"],
            printed_page=page,
        )
        message = "اقتراحات مطابقة عناوين فقط؛ الملاءمة العلمية غير مثبتة. اختر بعد المعاينة."
    elif command.startswith("history:"):
        cursor = command.split(":", 1)[1]
        history = services.read_citation_history(
            **common, before_revision=None if cursor == "latest" else _integer(cursor)
        )
    elif command == "cancel_correction":
        state["correcting"] = None
    elif command.startswith("correct:"):
        index = command.split(":", 1)[1]
        if not index.isascii() or not index.isdigit() or len(index) > 2:
            raise InvalidForm("citation_command_invalid")
        index = int(index)
        if index >= len(state["selections"]) or not state["selections"][index].get("citation_id"):
            raise InvalidForm("saved_citation_required")
        state["correcting"] = state["selections"][index]["citation_id"]
        message = "اختر الموضع المصحح من النتائج، واكتب سبب التصحيح في حقل التعليق قبل اختياره."
    elif command.startswith(("add:", "accept:", "replace:")):
        values = command.split(":")
        if len(values) != 3:
            raise InvalidForm("citation_command_invalid")
        operation = values[0]
        edition, row = _integer(values[1]), _integer(values[2])
        source = services.read_source(**common, edition_id=edition, source_row_id=row)
        if operation == "accept" and not any(
            candidate["source"]["edition_id"] == edition
            and candidate["source"]["source_row_id"] == row
            and candidate["source_sha256"] == source["source_sha256"]
            for candidate in state["suggestions"]
        ):
            raise InvalidForm("existing_proposal_required")
        target = (
            next(
                (
                    item
                    for item in state["selections"]
                    if state["correcting"] is not None
                    and item.get("citation_id") == state["correcting"]
                ),
                None,
            )
            if operation == "replace"
            else None
        )
        if operation == "replace" and (state["correcting"] is None or target is None):
            raise InvalidForm("saved_citation_required")
        if any(
            item is not target and item["edition_id"] == edition and item["source_row_id"] == row
            for item in state["selections"]
        ):
            message = "هذا الموضع موجود في القائمة؛ لم تتكرر الإحالة."
        elif operation == "replace":
            cases._text(fields["editorial_note"])
            target.update(
                edition_id=edition,
                source_row_id=row,
                source_sha256=source["source_sha256"],
                correction_reason=fields["editorial_note"],
            )
            state["correcting"] = None
            message = "أُعد التصحيح مع سببه؛ يلزم حفظ إصدار جديد ومراجعة المفتي."
        elif len(state["selections"]) >= services.MAX_CITATIONS:
            message, status = "بلغت القائمة حد 12 إحالة؛ احذف موضعًا قبل إضافة آخر.", 409
        else:
            state["selections"].append(
                dict(
                    edition_id=edition,
                    source_row_id=row,
                    source_sha256=source["source_sha256"],
                    editorial_note=fields["editorial_note"],
                )
            )
            message = "أُضيف الموضع إلى قائمة التحرير؛ لم يُحفظ إصدار جواب بعد."
    elif command.startswith(("remove:", "note:", "up:", "down:")):
        operation, index = command.split(":", 1)
        if not index.isascii() or not index.isdigit() or len(index) > 2:
            raise InvalidForm("citation_command_invalid")
        index = int(index)
        if index >= len(state["selections"]):
            raise InvalidForm("citation_selection_unavailable")
        if operation == "remove":
            state["selections"].pop(index)
        elif operation == "note":
            state["selections"][index]["editorial_note"] = fields["editorial_note"]
        else:
            destination = index + (-1 if operation == "up" else 1)
            if not 0 <= destination < len(state["selections"]):
                raise InvalidForm("citation_order_boundary")
            items = state["selections"]
            items[index], items[destination] = items[destination], items[index]
    elif command == "save":
        if fields.get("confirm") != "yes":
            raise InvalidForm("human_citation_review_required")
        try:
            selected = services.save_cited_answer(
                **common,
                text=fields["text"],
                selections=[
                    {
                        key: item[key]
                        for key in (
                            "edition_id",
                            "source_row_id",
                            "source_sha256",
                            "editorial_note",
                        )
                    }
                    for item in state["selections"]
                ],
                corrections=[
                    dict(
                        ordinal=index + 1,
                        previous_id=item["citation_id"],
                        reason=item["correction_reason"],
                    )
                    for index, item in enumerate(state["selections"])
                    if "correction_reason" in item
                ],
                expected_revision=state["revision"],
                expected_evidence_version=state["evidence_version"],
            )
        except cases.CaseConflict:
            # Keep the submitted draft and old pins for copying/review. Never
            # silently bind a failed submission to current evidence/revision.
            message, status = (
                "لم يُحفظ الجواب: راجع حداثة القضية والوقائع والقائمة. نصك وقائمتك باقيان "
                "هنا للنسخ، ولم تُستبدل مراجعتهما بمراجعة أحدث. أعد فتح المحرر بعد المراجعة.",
                409,
            )
        else:
            state["revision"] = selected["revision"]
            state["selections"] = [_selection(link) for link in services.read_citations(**common)]
            state["correcting"] = None
            state["suggestions"] = []
            message = "حُفظ إصدار جواب جديد بكل الإحالات المعروضة؛ أُلغي أي اعتماد سابق."
    elif command not in {"search", "return"}:
        raise InvalidForm("citation_command_invalid")
    return _page(
        request,
        common,
        selected,
        state,
        text=fields["text"],
        query=fields["query"],
        edition_id=edition_id,
        part=fields["part"],
        page=page,
        editorial_note=fields["editorial_note"],
        message=message,
        status=status,
        opened=opened,
        history=history,
    )
