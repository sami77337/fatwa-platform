"""Review-bound taxonomy selection for canonical text search.

Taxonomy case and advisory locks are taken before the canonical search
boundary. Historical classification is never projected into another version.
Unfiltered search does not require taxonomy to be enabled.
"""
from contextlib import contextmanager

from django.apps import apps

from apps.casework import services as cases


class Selection:
    def __init__(self, guard, version, node_id, descendants):
        from apps.development_taxonomy import services as taxonomy

        self.guard, self.version = guard, version
        nodes = taxonomy.validate_tree(version.nodes)
        if node_id not in nodes:
            raise cases.CaseConflict("search_taxonomy_node_unavailable")
        self.node_id, self.descendants = node_id, descendants
        self.node_ids = {node_id}
        if descendants:
            for item in version.nodes:
                parent = item["parent"]
                while parent is not None:
                    if parent == node_id:
                        self.node_ids.add(item["id"])
                        break
                    parent = nodes[parent]["parent"]
        self.info = {
            "version_id": str(version.pk),
            "node_id": node_id,
            "children": descendants,
            "tree_title": version.tree.title,
            "version_number": version.number,
            "node_name": nodes[node_id]["name"],
        }

    def case_ids(self, cases_by_id):
        from apps.development_taxonomy import services as taxonomy

        selected = set()
        for case in cases_by_id.values():
            # Neither counts nor index states for excluded cases are exposed.
            if case.pk not in self.guard.locked or not self.guard.permit(
                case.pk, "SEARCH", required=False
            ):
                continue
            row = taxonomy._current(case.pk)
            if (
                row is None
                or row.version_id != self.version.pk
                or case.stage != "ANSWERED"
                or case.approved_answer_id != row.answer_id
                or case.evidence_version != row.evidence_version
            ):
                continue
            primary, additional = taxonomy._selection(
                self.version, row.primary_id, row.additional
            )
            if not ({primary, *additional} & self.node_ids):
                continue
            if self.guard.permit(
                case.pk, "READ",
                {"kind": "BINDING", "id": str(row.pk), "digest": row.digest},
                required=False,
            ):
                selected.add(str(case.pk))
        return frozenset(selected)


@contextmanager
def reviewed_selector(
    *, case_id, subject_id, provider, synthetic_fixtures_only=False,
    version_id=None, node_id=None, descendants=False,
):
    if version_id is None and node_id is None and descendants is False:
        yield None
        return
    if (
        type(version_id) is not str or type(node_id) is not str
        or type(descendants) is not bool or not version_id or not node_id
    ):
        raise cases.CaseConflict("search_taxonomy_selection_invalid")
    if not apps.is_installed("apps.development_taxonomy"):
        raise cases.CaseConflict("search_taxonomy_unavailable")
    from apps.development_taxonomy import boundary, services as taxonomy

    selected_id = str(cases._uuid(node_id))
    with boundary.scope(
        case_id=case_id,
        subject_id=subject_id,
        provider=provider,
        synthetic_fixtures_only=synthetic_fixtures_only,
    ) as guard:
        version = taxonomy._version(guard, version_id, reviewed=True)
        guard.permit(
            version.tree.case_id, "SEARCH",
            {"kind": "TREE", "id": str(version.tree_id), "digest": version.tree.digest},
        )
        guard.permit(
            version.tree.case_id, "READ",
            {"kind": "VERSION", "id": str(version.pk), "digest": version.digest},
        )
        yield Selection(guard, version, selected_id, descendants)
