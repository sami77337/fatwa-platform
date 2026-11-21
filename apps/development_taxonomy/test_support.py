"""Explicit synthetic concepts; no real taxonomy or reference corpus inferred."""

import uuid
from dataclasses import replace

from django.test import override_settings

from apps.casework import services as cases
from apps.experimental_publication.tests import Directory
from apps.research_library.test_support import bind_identity_snapshot
from tests.casework.test_http import WEB_SETTINGS

from . import services
from .authority import TaxonomyAuthority
from .models import TreeVersion

FEATURES = {
    **{key: value for key, value in WEB_SETTINGS.items() if not key.startswith("DATA_UPLOAD_")},
    "ROOT_URLCONF": "config.campaign_urls",
    "FATWA_DEVELOPMENT_TAXONOMY_ENABLED": True,
}


class Authority(TaxonomyAuthority):
    def __init__(self, refs):
        self.refs, self.denied, self.hook = set(refs), set(), None

    def projection_epoch(self):
        return repr((sorted(self.refs), sorted(self.denied, key=repr)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        return (
            values["provider_id"] == "synthetic-publication-directory"
            and values["subject_id"] in {"editor", "other", "publisher"}
            and values["auth_epoch"] == "epoch-1"
            and values["case_ref"] in self.refs
            and values["action"]
            in {
                "READ",
                "SEARCH",
                "CREATE_TREE",
                "EDIT",
                "REVIEW",
                "USE",
                "BIND",
                "MAP",
                "REVIEW_MAPPING",
                "MIGRATE",
                "ROLLBACK",
            }
            and values["action"] not in self.denied
            and (values["action"], values["case_ref"]) not in self.denied
        )


def initial_nodes():
    return [
        {
            "key": "new:0",
            "parent": "",
            "name": "جذر فقهي اصطناعي",
            "definition": "مفهوم تجريبي للجذر؛ ليس بابًا علميًا معتمدًا",
        },
        {
            "key": "new:1",
            "parent": "new:0",
            "name": "باب اصطناعي ألف",
            "definition": "مفهوم تجريبي أول ثابت",
        },
        {
            "key": "new:2",
            "parent": "new:1",
            "name": "مسألة اصطناعية دقيقة",
            "definition": "مفهوم تجريبي فرعي ثابت",
        },
        {
            "key": "new:3",
            "parent": "new:0",
            "name": "باب اصطناعي باء",
            "definition": "مفهوم تجريبي ثانٍ ثابت",
        },
    ]


class TaxonomyFixture:
    def setUp(self):
        super().setUp()
        key = uuid.uuid4().hex
        self.receipt = cases.intake_case(
            original_question="سؤال اصطناعي لتصنيف مستقل",
            source_event_id="taxonomy-" + key,
            requester_id="synthetic-taxonomy-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        self.directory = bind_identity_snapshot(Directory([self.receipt["public_ref"]]))
        self.directory.authenticate = lambda credential: self.directory.resolve(
            {
                "synthetic-editor-credential-32-characters": "editor",
                "synthetic-reviewer-credential-32-characters": "other",
                "synthetic-publisher-credential-32-characters": "publisher",
            }.get(credential, "")
        )
        self.authority = Authority([self.receipt["public_ref"]])
        configured = override_settings(
            FATWA_CASEWORK_IDENTITY_PROVIDER=self.directory,
            FATWA_DEVELOPMENT_TAXONOMY_AUTHORITY=self.authority,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.common = dict(
            case_id=self.receipt["case_id"],
            subject_id="editor",
            provider=self.directory,
            synthetic_fixtures_only=True,
        )
        self.approved(self.common)

    def approved(self, base):
        row = cases.save_answer(
            **base,
            text="جواب اصطناعي لا يمثل فتوى حقيقية",
            expected_revision=1,
            expected_evidence_version=1,
        )
        cases.record_decision(
            **{**base, "subject_id": "other"},
            answer_id=row["answers"][-1]["id"],
            action="APPROVE",
            expected_revision=2,
            expected_evidence_version=1,
        )

    def state(self, base=None, version=None):
        return services.desk(**(base or self.common), version_id=version)

    def command(self, base=None):
        state = self.state(base)
        return dict(
            **(base or self.common),
            expected_snapshot=state["snapshot"],
            expected_revision=state["revision"],
            expected_evidence_version=state["evidence_version"],
            request_key=uuid.uuid4(),
        )

    def save(self, nodes=None, tree=None, **changes):
        values = dict(
            **self.command(),
            nodes=nodes if nodes is not None else initial_nodes(),
            tree_id=tree["tree_id"] if tree else None,
            expected_number=tree["number"] if tree else 0,
            title="شجرة فقهية اصطناعية مستقلة",
            provenance="أسماء ومعانٍ اصطناعية صرفة للتطوير؛ لا مصدر شرعي أو قبول نهائي",
            reason="نسخة بشرية موثقة للاختبار",
            confirmed=True,
        )
        return services.save_version(**(values | changes))

    def review(self, row, kind="VERSION", base=None):
        reviewer = {**(base or self.common), "subject_id": "other"}
        services.review(
            **self.command(reviewer),
            target_kind=kind,
            target_id=row["id"],
            action="APPROVE",
            reason="مراجعة مستقلة للنسخة والأثر الاصطناعي",
            confirmed=True,
        )
        return row

    def nodes(self, version):
        dto = self.state(version=version["id"])["selected"]
        return [
            {
                "key": node["id"],
                "parent": node["parent"] or "",
                "name": node["name"],
                "definition": node["definition"],
            }
            for node in dto["nodes"]
        ]

    def bind(self, version, base=None, primary_index=1, additional_indices=(3,)):
        nodes = TreeVersion.objects.get(pk=version["id"]).nodes
        return services.bind(
            **self.command(base),
            version_id=version["id"],
            primary=nodes[primary_index]["id"],
            additional=[nodes[index]["id"] for index in additional_indices],
            reason="تصنيف بشري صريح للمسألة المركبة الاصطناعية",
            confirmed=True,
        )

    def renamed(self, source):
        nodes = self.nodes(source)
        nodes[1]["name"] = "باب ألف بعد إعادة تسمية"
        nodes[2]["parent"] = nodes[3]["key"]
        target = self.review(self.save(nodes, tree=source))
        mapping = [
            {
                "source": row["key"],
                "kind": "RENAMED" if i == 1 else "MOVED" if i == 2 else "SAME",
                "targets": [row["key"]],
                "reason": "تتبع إنساني للمعنى المستقر",
            }
            for i, row in enumerate(nodes)
        ]
        return target, mapping

    def plan(self, source, target, mapping, resolutions=None):
        preview = services.preview(
            **self.common,
            source_version_id=source["id"],
            target_version_id=target["id"],
            mapping=mapping,
        )
        if resolutions is None:
            resolutions = [
                {
                    "case_id": item["case_id"],
                    "hold": False,
                    "primary": item["before"]["primary"],
                    "additional": item["before"]["additional"],
                    "reason": "نقل واضح بنفس الهوية الثابتة",
                }
                for item in preview["impacts"]
            ]
        row = services.save_plan(
            **self.command(),
            source_version_id=source["id"],
            target_version_id=target["id"],
            mapping=mapping,
            resolutions=resolutions,
            reason="خطة نقل ذات أثر محدد",
            confirmed=True,
        )
        return row

    def new_case(self):
        key = uuid.uuid4().hex
        receipt = cases.intake_case(
            original_question="سؤال ثانٍ مستقل للتصنيف",
            source_event_id=key,
            requester_id="synthetic-" + key,
            idempotency_key=key,
            synthetic_fixtures_only=True,
        )
        for subject, actor in self.directory.identities.items():
            self.directory.identities[subject] = replace(
                actor, case_keys=actor.case_keys | {receipt["public_ref"]}
            )
        self.authority.refs.add(receipt["public_ref"])
        base = {**self.common, "case_id": receipt["case_id"]}
        self.approved(base)
        return receipt, base
