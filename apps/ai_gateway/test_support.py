"""Declared synthetic adapter and exact fixture grants, never production defaults."""

import json
import uuid
from hashlib import sha256

from django.test import override_settings

from apps.precise_citations.test_support import FEATURES as CITATION_FEATURES
from apps.precise_citations.test_support import CitationFixture

from . import services
from .authority import GatewayAuthority
from .contract import CitationProvider, ProviderSpec

FEATURES = {
    **CITATION_FEATURES,
    "FATWA_AI_GATEWAY_ENABLED": True,
    "FATWA_AI_CITATION_CANDIDATES_ENABLED": True,
    "FATWA_AI_DISABLED_PROVIDERS": frozenset(),
}


class SyntheticProvider(CitationProvider):
    def __init__(self, source_id):
        self.spec = ProviderSpec(
            "synthetic-citation-fixture",
            "synthetic-citation-model",
            "synthetic-ranges-v1",
            "fixture-adapter-v1",
            "SYNTHETIC",
        )
        self.source_id = source_id
        self.calls, self.raw, self.error, self.hook = [], None, None, None

    def output(self):
        return {"candidates": [{"source_id": self.source_id, "start": 0, "end": 12}]}

    def generate(self, request):
        self.calls.append(request)
        if self.hook:
            self.hook()
        if self.error:
            raise self.error
        return self.raw if self.raw is not None else json.dumps(self.output()).encode()


class FixtureAuthority(GatewayAuthority):
    def __init__(self, receipt, material, query="عبارة محددة"):
        query_digest = sha256(query.encode()).hexdigest()
        self.receipt = receipt
        self.processing = {
            ("DRAFT_FRAGMENT", query_digest, query_digest),
            ("LIBRARY", material["version_id"], material["digest"]),
        }
        self.denied, self.hook = set(), None

    def projection_epoch(self):
        return repr((self.receipt, sorted(self.processing), sorted(self.denied)))

    def permits(self, **values):
        if self.hook:
            self.hook(values)
        if (
            values["provider_id"] != "synthetic-publication-directory"
            or values["subject_id"] not in {"editor", "other"}
            or values["auth_epoch"] != "epoch-1"
            or values["case_ref"] != self.receipt["public_ref"]
            or values["task"] != "CITATION_CANDIDATES"
            or (values["action"], values["resource_kind"]) in self.denied
        ):
            return False
        if values["action"] == "USE":
            return (values["resource_kind"], values["resource_id"], values["resource_digest"]) == (
                "CASE",
                str(self.receipt["case_id"]),
                "",
            )
        return (
            values["action"] == "PROCESS_CONTEXT"
            and values["destination_provider"] == "synthetic-citation-fixture"
            and values["model_id"] == "synthetic-citation-model"
            and values["model_version"] == "synthetic-ranges-v1"
            and (values["resource_kind"], values["resource_id"], values["resource_digest"])
            in self.processing
        )


class GatewayFixture(CitationFixture):
    def setUp(self):
        super().setUp()
        self.source_text = "مصدر اصطناعي دقيق محفوظ للإحالة"
        self.ai_provider = SyntheticProvider(self.material["version_id"])
        self.gateway_authority = FixtureAuthority(self.receipt, self.material)
        configured = override_settings(
            FATWA_AI_GATEWAY_AUTHORITY=self.gateway_authority,
            FATWA_AI_CITATION_PROVIDER=self.ai_provider,
        )
        configured.enable()
        self.addCleanup(configured.disable)

    def request(self, **changes):
        values = dict(
            self.common,
            query="عبارة محددة",
            selection="LIBRARY:" + self.material["version_id"],
            start=0,
            end=24,
            expected_revision=1,
            expected_evidence_version=1,
            request_key=uuid.uuid4(),
        )
        return services.request_candidates(**{**values, **changes})
