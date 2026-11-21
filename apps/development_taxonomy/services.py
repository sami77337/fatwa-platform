"""Versioned provisional fiqh concepts, human bindings and reviewed migrations."""

import uuid

from apps.casework import services as cases
from apps.platform_recovery.integration import mutation_service

from .boundary import scope, seal, text, verify
from .models import (
    CaseClassification,
    Concept,
    DevelopmentTree,
    HumanReview,
    MigrationExecution,
    MigrationPlan,
    TreeVersion,
)

MAX_NODES = 64
MAX_MAPPING_EDGES = 256
MAPPING_KINDS = ("SAME", "RENAMED", "MOVED", "SPLIT", "MERGED", "NO_EQUIVALENT")


def _tree(guard, tree_id, action="READ"):
    row = DevelopmentTree.objects.filter(pk=cases._uuid(tree_id), case_id__in=guard.locked).first()
    if row is None:
        raise cases.CaseConflict("development_taxonomy_unavailable")
    verify(row)
    guard.permit(row.case_id, action, {"kind": "TREE", "id": str(row.pk), "digest": row.digest})
    return row


def _version(guard, version_id, *, reviewed=False, action="READ"):
    row = (
        TreeVersion.objects.select_related("tree")
        .filter(pk=cases._uuid(version_id), tree__case_id__in=guard.locked)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("development_taxonomy_unavailable")
    _tree(guard, row.tree_id, action)
    verify(row)
    validate_tree(row.nodes)
    concepts = {
        str(item.pk): item
        for item in Concept.objects.filter(tree=row.tree, pk__in=[node["id"] for node in row.nodes])
    }
    if len(concepts) != len(row.nodes):
        raise cases.CaseConflict("development_taxonomy_concept_missing")
    for concept in concepts.values():
        verify(concept)
    review = HumanReview.objects.filter(version=row).first()
    if review:
        verify(review)
        if review.content_digest != row.digest:
            raise cases.CaseConflict("development_taxonomy_review_changed")
    if reviewed and (review is None or review.action != "APPROVE"):
        raise cases.CaseConflict("development_taxonomy_human_review_required")
    return row


def validate_tree(nodes):
    if type(nodes) is not list or not 1 <= len(nodes) <= MAX_NODES:
        raise cases.CaseConflict("development_taxonomy_node_bound")
    by_id = {}
    for index, row in enumerate(nodes, 1):
        if (
            type(row) is not dict
            or set(row) != {"id", "parent", "name", "order"}
            or row["order"] != index
        ):
            raise cases.CaseConflict("development_taxonomy_node_invalid")
        identifier = str(cases._uuid(row["id"]))
        if identifier in by_id:
            raise cases.CaseConflict("development_taxonomy_duplicate_concept")
        text(row["name"], 160)
        if row["parent"] is not None:
            cases._uuid(row["parent"])
        by_id[identifier] = row
    for identifier in by_id:
        seen, current = set(), identifier
        while current is not None:
            if current in seen or current not in by_id or len(seen) >= 8:
                raise cases.CaseConflict("development_taxonomy_cycle_or_depth")
            seen.add(current)
            current = by_id[current]["parent"]
    return by_id


def _normalize(tree, nodes):
    if type(nodes) is not list or not 1 <= len(nodes) <= MAX_NODES:
        raise cases.CaseConflict("development_taxonomy_node_bound")
    existing = {str(row.pk): row for row in Concept.objects.filter(tree=tree)} if tree else {}
    keys, creates = {}, []
    for row in nodes:
        if type(row) is not dict or set(row) != {"key", "name", "parent", "definition"}:
            raise cases.CaseConflict("development_taxonomy_draft_invalid")
        key = row["key"]
        if type(key) is not str or key in keys or len(key) > 48:
            raise cases.CaseConflict("development_taxonomy_draft_key")
        text(row["name"], 160)
        text(row["definition"], 1000)
        if key.startswith("new:") and key[4:].isascii() and key[4:].isdigit():
            identifier = uuid.uuid4()
            creates.append((identifier, row["definition"]))
        else:
            identifier = cases._uuid(key)
            concept = existing.get(str(identifier))
            if concept is None:
                raise cases.CaseConflict("development_taxonomy_concept_unavailable")
            verify(concept)
            if concept.definition != row["definition"]:
                raise cases.CaseConflict("development_taxonomy_stable_meaning_required")
        keys[key] = str(identifier)
    result = []
    for index, row in enumerate(nodes, 1):
        parent = keys.get(row["parent"]) if row["parent"] else None
        if row["parent"] and parent is None:
            raise cases.CaseConflict("development_taxonomy_parent_unavailable")
        result.append(
            {"id": keys[row["key"]], "parent": parent, "name": row["name"], "order": index}
        )
    validate_tree(result)
    return result, creates


def _current(case_id):
    rows = list(CaseClassification.objects.filter(case_id=case_id).order_by("sequence")[:2049])
    if len(rows) > 2048:
        raise cases.CaseConflict("development_taxonomy_binding_bound")
    previous = None
    for index, row in enumerate(rows, 1):
        verify(row)
        if row.sequence != index or row.previous_id != (previous.pk if previous else None):
            raise cases.CaseConflict("development_taxonomy_binding_history")
        previous = row
    return previous


def _selection(version, primary, additional):
    primary = str(cases._uuid(primary))
    if type(additional) is not list or len(additional) > 12:
        raise cases.CaseConflict("development_taxonomy_selection_bound")
    additional = [str(cases._uuid(value)) for value in additional]
    ids = set(validate_tree(version.nodes))
    if (
        primary not in ids
        or primary in additional
        or len(set(additional)) != len(additional)
        or not set(additional) <= ids
    ):
        raise cases.CaseConflict("development_taxonomy_selection_invalid")
    return primary, additional


def _approved_case(guard, case_id):
    case = guard.locked.get(cases._uuid(case_id))
    if case is None:
        raise cases.CaseConflict("development_taxonomy_unavailable")
    guard.permit(case.pk, "READ")
    cases._verify(case)
    if case.stage != "ANSWERED" or not case.approved_answer_id:
        raise cases.CaseConflict("development_taxonomy_approved_answer_required")
    return case


def _state(row):
    verify(row)
    review = HumanReview.objects.filter(version=row).first()
    if review:
        verify(review)
        if review.content_digest != row.digest:
            raise cases.CaseConflict("development_taxonomy_review_changed")
    return review.action if review else "DRAFT"


def version_dto(guard, row):
    row = _version(guard, row.pk)
    concepts = {str(item.pk): item for item in Concept.objects.filter(tree=row.tree)}
    by_id = validate_tree(row.nodes)
    nodes = []
    for item in row.nodes:
        names, parent = [item["name"]], item["parent"]
        while parent:
            names.insert(0, by_id[parent]["name"])
            parent = by_id[parent]["parent"]
        nodes.append(
            {
                **item,
                "definition": concepts[item["id"]].definition,
                "path": " / ".join(names),
                "depth": len(names),
            }
        )

    def outline(parent=None):
        return [
            {**node, "children": outline(node["id"])} for node in nodes if node["parent"] == parent
        ]

    return {
        "outline": outline(),
        "id": str(row.pk),
        "tree_id": str(row.tree_id),
        "title": row.tree.title,
        "provenance": row.tree.provenance,
        "number": row.number,
        "digest": row.digest,
        "nodes": nodes,
        "state": _state(row),
        "author": row.subject_id,
        "independent": (row.provider_id, row.subject_id)
        != (guard.provider.provider_id, guard.actor.subject_id),
        "reason": row.reason,
    }


def binding_dto(guard, row):
    version = _version(guard, row.version_id)
    by_id = validate_tree(version.nodes)
    _selection(version, row.primary_id, row.additional)
    guard.permit(row.case_id, "READ", {"kind": "BINDING", "id": str(row.pk), "digest": row.digest})
    case = guard.locked[row.case_id]
    return {
        "id": str(row.pk),
        "sequence": row.sequence,
        "version_id": str(version.pk),
        "version_number": version.number,
        "tree_title": version.tree.title,
        "primary_id": str(row.primary_id),
        "primary": by_id[str(row.primary_id)]["name"],
        "additional_ids": row.additional,
        "additional": [by_id[value]["name"] for value in row.additional],
        "answer_id": str(row.answer_id),
        "current_answer": case.approved_answer_id == row.answer_id
        and case.evidence_version == row.evidence_version,
        "reason": row.reason,
        "created_at": row.created_at,
        "actor": row.subject_id,
        "digest": row.digest,
    }


def desk_locked(guard, *, case_id, version_id=None):
    case = guard.locked[cases._uuid(case_id)]
    trees, versions = [], []
    for tree in DevelopmentTree.objects.filter(case_id__in=guard.locked).order_by(
        "created_at", "pk"
    )[:33]:
        if not guard.permit(
            tree.case_id, "SEARCH", {"kind": "TREE", "id": str(tree.pk)}, required=False
        ):
            continue
        _tree(guard, tree.pk)
        history = list(TreeVersion.objects.filter(tree=tree).order_by("number")[:2049])
        if not history or len(history) > 2048:
            raise cases.CaseConflict("development_taxonomy_version_bound")
        for row in history:
            versions.append(
                {
                    "id": str(row.pk),
                    "tree_id": str(tree.pk),
                    "title": tree.title,
                    "number": row.number,
                    "state": _state(row),
                }
            )
        trees.append(
            {
                "id": str(tree.pk),
                "title": tree.title,
                "latest_id": str(history[-1].pk),
                "number": history[-1].number,
            }
        )
    if len(trees) > 32:
        raise cases.CaseConflict("development_taxonomy_registry_bound")
    selected = version_dto(guard, _version(guard, version_id)) if version_id else None
    current = _current(case.pk)
    binding = binding_dto(guard, current) if current else None
    history = [
        binding_dto(guard, row)
        for row in CaseClassification.objects.filter(case=case).order_by("sequence")
    ]
    plans = []
    for plan in MigrationPlan.objects.filter(tree_id__in=[row["id"] for row in trees]).order_by(
        "created_at", "pk"
    )[:65]:
        if {cases._uuid(item["case_id"]) for item in plan.manifest} <= guard.locked.keys():
            plans.append(plan_dto(guard, plan))
    return {
        "case_id": str(case.pk),
        "case_ref": case.public_ref,
        "revision": case.revision,
        "evidence_version": case.evidence_version,
        "snapshot": guard.watermark,
        "trees": trees,
        "versions": versions,
        "selected": selected,
        "binding": binding,
        "history": history,
        "plans": plans,
        "can_bind": case.approved_answer_id is not None and case.stage == "ANSWERED",
    }


@mutation_service
def desk(*, version_id=None, **base):
    with scope(**base) as guard:
        return desk_locked(guard, case_id=base["case_id"], version_id=version_id)


def _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version):
    guard.before_write(
        expected_snapshot, base["case_id"], expected_revision, expected_evidence_version
    )


@mutation_service
def save_version(
    *,
    tree_id=None,
    title="",
    provenance="",
    nodes,
    reason,
    expected_number,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    confirmed=False,
    **base,
):
    text(reason, 2000)
    if confirmed is not True:
        raise cases.CaseConflict("development_taxonomy_confirmation_required")
    with scope(**base) as guard:
        tree, previous = None, None
        if tree_id:
            tree = _tree(guard, tree_id, "EDIT")
            previous = TreeVersion.objects.filter(tree=tree).order_by("-number").first()
            if previous is None or previous.number != expected_number:
                raise cases.CaseConflict("development_taxonomy_version_changed")
        else:
            text(title, 160)
            text(provenance, 2000)
            if expected_number != 0:
                raise cases.CaseConflict("development_taxonomy_version_changed")
            guard.permit(base["case_id"], "CREATE_TREE")
        normalized, new_concepts = _normalize(tree, nodes)
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        if tree is None:
            tree = seal(
                DevelopmentTree(
                    case_id=base["case_id"],
                    title=title,
                    provenance=provenance,
                    **guard.actor_values(),
                )
            )
        for identifier, definition in new_concepts:
            seal(Concept(id=identifier, tree=tree, definition=definition, **guard.actor_values()))
        row = seal(
            TreeVersion(
                tree=tree,
                number=previous.number + 1 if previous else 1,
                previous=previous,
                nodes=normalized,
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk), "tree_id": str(tree.pk), "number": row.number}


@mutation_service
def review(
    *,
    target_kind,
    target_id,
    action,
    reason,
    confirmed,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    **base,
):
    text(reason, 2000)
    if (
        confirmed is not True
        or action not in {"APPROVE", "REJECT"}
        or target_kind not in {"VERSION", "PLAN"}
    ):
        raise cases.CaseConflict("development_taxonomy_review_invalid")
    with scope(**base) as guard:
        if target_kind == "VERSION":
            row = _version(guard, target_id, action="REVIEW")
            if (
                TreeVersion.objects.filter(tree=row.tree, number__gt=row.number).exists()
                or HumanReview.objects.filter(version=row).exists()
            ):
                raise cases.CaseConflict("development_taxonomy_review_changed")
            target = {"version": row}
        else:
            row = _plan(guard, target_id, "REVIEW_MAPPING")
            if HumanReview.objects.filter(plan=row).exists():
                raise cases.CaseConflict("development_taxonomy_review_changed")
            _check_manifest(guard, row)
            target = {"plan": row}
        if (row.provider_id, row.subject_id) == (
            guard.provider.provider_id,
            guard.actor.subject_id,
        ):
            raise cases.CaseConflict("development_taxonomy_independent_review_required")
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        record = seal(
            HumanReview(
                **target,
                action=action,
                content_digest=row.digest,
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(record.pk)}


@mutation_service
def bind(
    *,
    version_id,
    primary,
    additional,
    reason,
    confirmed,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    **base,
):
    text(reason, 2000)
    if confirmed is not True:
        raise cases.CaseConflict("development_taxonomy_confirmation_required")
    with scope(**base) as guard:
        version = _version(guard, version_id, reviewed=True, action="USE")
        primary, additional = _selection(version, primary, additional)
        case = _approved_case(guard, base["case_id"])
        guard.permit(case.pk, "BIND", {"version": str(version.pk), "digest": version.digest})
        previous = _current(case.pk)
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        row = seal(
            CaseClassification(
                case=case,
                answer_id=case.approved_answer_id,
                evidence_version=case.evidence_version,
                sequence=previous.sequence + 1 if previous else 1,
                previous=previous,
                version=version,
                primary_id=primary,
                additional=additional,
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk), "sequence": row.sequence}


def validate_mapping(source, target, mapping):
    old, new = validate_tree(source.nodes), validate_tree(target.nodes)
    if (
        source.tree_id != target.tree_id
        or source.number >= target.number
        or type(mapping) is not list
        or len(mapping) != len(old)
    ):
        raise cases.CaseConflict("development_taxonomy_mapping_invalid")
    result, edges = {}, 0
    for row in mapping:
        if type(row) is not dict or set(row) != {"source", "kind", "targets", "reason"}:
            raise cases.CaseConflict("development_taxonomy_mapping_invalid")
        key, kind, targets = row["source"], row["kind"], row["targets"]
        text(row["reason"], 1000)
        if (
            key not in old
            or key in result
            or kind not in MAPPING_KINDS
            or type(targets) is not list
            or any(type(value) is not str for value in targets)
            or len(set(targets)) != len(targets)
            or not set(targets) <= new.keys()
        ):
            raise cases.CaseConflict("development_taxonomy_mapping_invalid")
        edges += len(targets)
        if edges > MAX_MAPPING_EDGES:
            raise cases.CaseConflict("development_taxonomy_mapping_edge_bound")
        if kind in {"SAME", "RENAMED", "MOVED"}:
            if targets != [key] or key not in new:
                raise cases.CaseConflict("development_taxonomy_stable_identity_mapping")
            renamed = old[key]["name"] != new[key]["name"]
            moved = (old[key]["parent"], old[key]["order"]) != (
                new[key]["parent"],
                new[key]["order"],
            )
            if (
                (kind == "SAME" and (renamed or moved))
                or (kind == "RENAMED" and not renamed)
                or (kind == "MOVED" and not moved)
            ):
                raise cases.CaseConflict("development_taxonomy_mapping_kind_mismatch")
        elif kind == "NO_EQUIVALENT":
            if targets or key in new:
                raise cases.CaseConflict("development_taxonomy_no_equivalent_mismatch")
        else:
            if (
                key in new
                or set(targets) & old.keys()
                or (kind == "SPLIT" and len(targets) < 2)
                or (kind == "MERGED" and len(targets) != 1)
            ):
                raise cases.CaseConflict("development_taxonomy_new_meaning_requires_new_id")
        result[key] = {**row, "targets": list(targets)}
    if set(result) != set(old):
        raise cases.CaseConflict("development_taxonomy_mapping_incomplete")
    for row in result.values():
        if (
            row["kind"] == "MERGED"
            and sum(
                other["kind"] == "MERGED" and other["targets"] == row["targets"]
                for other in result.values()
            )
            < 2
        ):
            raise cases.CaseConflict("development_taxonomy_merge_sources_required")
    return result


def preview_locked(guard, *, source_version_id, target_version_id, mapping):
    source = _version(guard, source_version_id, reviewed=True, action="MAP")
    target = _version(guard, target_version_id, reviewed=True, action="MAP")
    by_source = validate_mapping(source, target, mapping)
    new = validate_tree(target.nodes)
    # Discover only identities of candidate cases before callbacks. All cases
    # must already belong to the actor's sorted lock set; no hidden counts leak.
    candidate_ids = set(
        CaseClassification.objects.filter(version__tree=source.tree).values_list(
            "case_id", flat=True
        )
    )
    if not candidate_ids <= guard.locked.keys() or len(candidate_ids) > 32:
        raise cases.CaseConflict("development_taxonomy_complete_scope_required")
    impacts = []
    for identifier in sorted(candidate_ids):
        current = _current(identifier)
        if current.version_id != source.pk:
            continue
        case = _approved_case(guard, identifier)
        guard.permit(case.pk, "MAP", {"binding": str(current.pk), "digest": current.digest})
        if (
            current.answer_id != case.approved_answer_id
            or current.evidence_version != case.evidence_version
        ):
            raise cases.CaseConflict("development_taxonomy_stale_answer_binding")
        original_ids = [str(current.primary_id), *current.additional]
        possible = set(value for key in original_ids for value in by_source[key]["targets"])
        unresolved = any(not by_source[key]["targets"] for key in original_ids)
        impacts.append(
            {
                "case_id": str(case.pk),
                "case_ref": case.public_ref,
                "case_revision": case.revision,
                "evidence_version": case.evidence_version,
                "answer_id": str(case.approved_answer_id),
                "before_id": str(current.pk),
                "before_digest": current.digest,
                "before": {
                    "version_id": str(source.pk),
                    "primary": str(current.primary_id),
                    "additional": current.additional,
                },
                "requires_hold": unresolved,
                "choices": [{"id": key, "name": new[key]["name"]} for key in sorted(possible)],
            }
        )
    return {
        "source_version_id": str(source.pk),
        "target_version_id": str(target.pk),
        "source_number": source.number,
        "target_number": target.number,
        "tree_id": str(source.tree_id),
        "mapping": [by_source[node["id"]] for node in source.nodes],
        "impacts": impacts,
        "snapshot": guard.watermark,
    }


@mutation_service
def preview(*, source_version_id, target_version_id, mapping, **base):
    with scope(**base) as guard:
        return preview_locked(
            guard,
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            mapping=mapping,
        )


@mutation_service
def save_plan(
    *,
    source_version_id,
    target_version_id,
    mapping,
    resolutions,
    reason,
    confirmed,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    **base,
):
    text(reason, 2000)
    if confirmed is not True or type(resolutions) is not list:
        raise cases.CaseConflict("development_taxonomy_confirmation_required")
    with scope(**base) as guard:
        preview = preview_locked(
            guard,
            source_version_id=source_version_id,
            target_version_id=target_version_id,
            mapping=mapping,
        )
        if len(resolutions) != len(preview["impacts"]):
            raise cases.CaseConflict("development_taxonomy_every_case_resolution_required")
        selected = {}
        for row in resolutions:
            if (
                type(row) is not dict
                or set(row) != {"case_id", "hold", "primary", "additional", "reason"}
                or row["case_id"] in selected
                or type(row["hold"]) is not bool
            ):
                raise cases.CaseConflict("development_taxonomy_resolution_invalid")
            text(row["reason"], 1000)
            selected[row["case_id"]] = row
        manifest = []
        target = _version(guard, target_version_id, reviewed=True)
        maps = {row["source"]: row for row in preview["mapping"]}
        for impact in preview["impacts"]:
            resolution = selected.get(impact["case_id"])
            if resolution is None:
                raise cases.CaseConflict("development_taxonomy_every_case_resolution_required")
            after = None
            if resolution["hold"]:
                if resolution["primary"] or resolution["additional"]:
                    raise cases.CaseConflict("development_taxonomy_held_case_has_selection")
            else:
                if impact["requires_hold"]:
                    raise cases.CaseConflict("development_taxonomy_no_equivalent_requires_hold")
                primary, extra = _selection(target, resolution["primary"], resolution["additional"])
                chosen = {primary, *extra}
                allowed = {item["id"] for item in impact["choices"]}
                if not chosen <= allowed or any(
                    not (chosen & set(maps[key]["targets"]))
                    for key in [impact["before"]["primary"], *impact["before"]["additional"]]
                ):
                    raise cases.CaseConflict("development_taxonomy_unresolved_split_choice")
                after = {"version_id": str(target.pk), "primary": primary, "additional": extra}
            manifest.append(
                {
                    key: value
                    for key, value in impact.items()
                    if key not in {"choices", "requires_hold"}
                }
                | {"after": after, "resolution_reason": resolution["reason"]}
            )
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        row = seal(
            MigrationPlan(
                tree_id=preview["tree_id"],
                source_version_id=source_version_id,
                target_version=target,
                mapping=preview["mapping"],
                manifest=manifest,
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        guard.written()
        return {"id": str(row.pk), "digest": row.digest}


def _plan(guard, identifier, action="READ"):
    row = (
        MigrationPlan.objects.select_related("tree")
        .filter(pk=cases._uuid(identifier), tree__case_id__in=guard.locked)
        .first()
    )
    if row is None:
        raise cases.CaseConflict("development_taxonomy_unavailable")
    verify(row)
    _tree(guard, row.tree_id, action)
    source = _version(guard, row.source_version_id, reviewed=True)
    target = _version(guard, row.target_version_id, reviewed=True)
    validate_mapping(source, target, row.mapping)
    guard.use_cases(
        [item["case_id"] for item in row.manifest],
        action,
        {"kind": "PLAN", "id": str(row.pk), "digest": row.digest},
    )
    return row


def _check_manifest(guard, plan, execution=None):
    if execution is None:
        candidates = set(
            CaseClassification.objects.filter(version_id=plan.source_version_id).values_list(
                "case_id", flat=True
            )
        )
        current_ids = {
            identifier
            for identifier in candidates
            if _current(identifier).version_id == plan.source_version_id
        }
        if current_ids != {cases._uuid(item["case_id"]) for item in plan.manifest}:
            raise cases.CaseConflict("development_taxonomy_impact_set_changed")
    for item in plan.manifest:
        case = _approved_case(guard, item["case_id"])
        current = _current(case.pk)
        if (
            case.revision != item["case_revision"]
            or case.evidence_version != item["evidence_version"]
            or str(case.approved_answer_id) != item["answer_id"]
        ):
            raise cases.CaseConflict("development_taxonomy_case_changed")
        if execution is not None and item["after"] is not None:
            if (
                current is None
                or current.execution_id != execution.pk
                or str(current.previous_id) != item["before_id"]
            ):
                raise cases.CaseConflict("development_taxonomy_rollback_no_longer_exact")
        elif (
            current is None
            or str(current.pk) != item["before_id"]
            or current.digest != item["before_digest"]
        ):
            raise cases.CaseConflict("development_taxonomy_binding_changed")


def plan_dto(guard, row):
    row = _plan(guard, row.pk)
    review = HumanReview.objects.filter(plan=row).first()
    if review:
        verify(review)
    executions = list(MigrationExecution.objects.filter(plan=row).order_by("created_at", "pk"))
    for item in executions:
        verify(item)
    return {
        "id": str(row.pk),
        "title": row.tree.title,
        "source_number": row.source_version.number,
        "target_number": row.target_version.number,
        "state": review.action if review else "DRAFT",
        "manifest": row.manifest,
        "mapping": row.mapping,
        "reason": row.reason,
        "digest": row.digest,
        "independent": (row.provider_id, row.subject_id)
        != (guard.provider.provider_id, guard.actor.subject_id),
        "applied": any(item.kind == "APPLY" for item in executions),
        "rolled_back": any(item.kind == "ROLLBACK" for item in executions),
    }


@mutation_service
def execute(
    *,
    plan_id,
    kind,
    reason,
    confirmed,
    expected_snapshot,
    expected_revision,
    expected_evidence_version,
    request_key,
    **base,
):
    text(reason, 2000)
    if confirmed is not True or kind not in {"APPLY", "ROLLBACK"}:
        raise cases.CaseConflict("development_taxonomy_confirmation_required")
    with scope(**base) as guard:
        plan = _plan(guard, plan_id, "MIGRATE" if kind == "APPLY" else "ROLLBACK")
        review = HumanReview.objects.filter(
            plan=plan, action="APPROVE", content_digest=plan.digest
        ).first()
        if review is None:
            raise cases.CaseConflict("development_taxonomy_reviewed_mapping_required")
        verify(review)
        applied = MigrationExecution.objects.filter(plan=plan, kind="APPLY").first()
        if MigrationExecution.objects.filter(plan=plan, kind=kind).exists() or (
            kind == "ROLLBACK" and applied is None
        ):
            raise cases.CaseConflict("development_taxonomy_execution_changed")
        _check_manifest(guard, plan, execution=applied if kind == "ROLLBACK" else None)
        _start(guard, base, expected_snapshot, expected_revision, expected_evidence_version)
        changed = [item for item in plan.manifest if item["after"] is not None]
        execution = seal(
            MigrationExecution(
                plan=plan,
                kind=kind,
                previous=applied if kind == "ROLLBACK" else None,
                count=len(changed),
                reason=reason,
                request_key=cases._uuid(request_key),
                **guard.actor_values(),
            )
        )
        for item in changed:
            selection = item["after"] if kind == "APPLY" else item["before"]
            current = _current(item["case_id"])
            seal(
                CaseClassification(
                    case_id=item["case_id"],
                    answer_id=item["answer_id"],
                    evidence_version=item["evidence_version"],
                    sequence=current.sequence + 1,
                    previous=current,
                    version_id=selection["version_id"],
                    primary_id=selection["primary"],
                    additional=selection["additional"],
                    execution=execution,
                    reason=reason,
                    request_key=uuid.uuid4(),
                    **guard.actor_values(),
                )
            )
        guard.written()
        return {
            "id": str(execution.pk),
            "changed": len(changed),
            "held": len(plan.manifest) - len(changed),
        }
