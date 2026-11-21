"""Finite synthetic grants and the real existing source/search/AI owner services."""

import tempfile
import uuid
from dataclasses import replace
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.ai_gateway.test_support import FEATURES as AI_FEATURES
from apps.ai_gateway.test_support import GatewayFixture
from apps.canonical_search import services as search
from apps.canonical_search.test_support import FixtureAuthority as SearchAuthority
from apps.casework.models import Case
from config.settings import campaign_review

from . import catalog, services, store
from .authority import DerivedAuthority, Grant
from .journal import DerivedJournal

FEATURES = {
    **AI_FEATURES,
    "FATWA_CANONICAL_SEARCH_ENABLED": True,
    "FATWA_DERIVED_MAINTENANCE_ENABLED": False,
    "FATWA_STAFF_SESSIONS_ENABLED": False,
    "FATWA_STAFF_MFA_ENABLED": False,
    "MIDDLEWARE": list(campaign_review.MIDDLEWARE),
    "ROOT_URLCONF": "config.campaign_urls",
}


class Authority(DerivedAuthority):
    def __init__(self, directory, resources):
        self.directory = directory
        self.choices = tuple(resources)
        self.until = timezone.now() + timedelta(minutes=20)
        self.denied, self.hook = set(), None

    def projection_epoch(self):
        return catalog.canonical(
            [self.directory.provider_id, self.choices, sorted(self.denied), self.until.isoformat()]
        )

    def resources(self, **values):
        return self.choices

    def authorize(self, **values):
        actor = self.directory.resolve(values["subject_id"])
        resource = values["resource"]
        allowed = bool(
            actor
            and values["provider_id"] == self.directory.provider_id
            and values["role"] == actor.role
            and values["auth_epoch"] == actor.auth_epoch
            and actor.subject_id in {"editor", "admin"}
            and (actor.subject_id, values["action"]) not in self.denied
            and (
                values["action"] == "ENTER"
                and resource is None
                or values["action"] in {"READ_AUDIT", "CLEAR", "REBUILD", "RECONCILE"}
                and resource is not None
                and (resource["kind"], resource["id"]) in self.choices
                and resource["header_digest"]
                == catalog.target(resource["kind"], resource["id"]).header_digest
            )
        )
        if self.hook:
            self.hook(values)
        return Grant(self.until) if allowed else None


class Fixture(GatewayFixture):
    def setUp(self):
        super().setUp()
        actor = self.directory.identities["editor"]
        self.directory.identities["admin"] = replace(
            actor, subject_id="admin", role="ORGANIZER_ADMIN"
        )
        self.directory.identities["operator"] = replace(
            actor, subject_id="operator", role="ORGANIZER"
        )
        self.search_authority = SearchAuthority(self.receipt["public_ref"])
        search_config = override_settings(FATWA_CANONICAL_SEARCH_AUTHORITY=self.search_authority)
        search_config.enable()
        self.addCleanup(search_config.disable)
        case = Case.objects.get(pk=self.receipt["case_id"])
        self.built = search.rebuild(
            **self.common,
            expected_revision=case.revision,
            expected_evidence_version=case.evidence_version,
            expected_generation=0,
            request_key=uuid.uuid4(),
        )
        self.run = self.request()
        self.journal_root = tempfile.TemporaryDirectory(prefix="fatwa-derived-floor-")
        self.addCleanup(self.journal_root.cleanup)
        self.journal = DerivedJournal(root=self.journal_root.name, ledger_id=str(uuid.uuid4()))
        self.journal.initialize()
        self.maintenance_authority = Authority(
            self.directory,
            (("SEARCH_INDEX", self.built["generation_id"]), ("AI_CANDIDATES", self.run["id"])),
        )
        configured = override_settings(
            FATWA_DERIVED_MAINTENANCE_ENABLED=True,
            FATWA_DERIVED_MAINTENANCE_AUTHORITY=self.maintenance_authority,
            FATWA_DERIVED_MAINTENANCE_JOURNAL=self.journal,
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.base = dict(provider=self.directory, subject_id="editor", synthetic_fixtures_only=True)

    def proposal(self, action="CLEAR", kind="SEARCH_INDEX", **changes):
        identifier = self.built["generation_id"] if kind == "SEARCH_INDEX" else self.run["id"]
        if action == "RECONCILE":
            values = dict(
                kind="",
                identifier="",
                header_digest="",
                payload_digest="",
                clearance="",
                watermark=store.snapshot(allow_pending=True).watermark,
            )
        else:
            with services.inspect(kind=kind, identifier=identifier, **self.base) as inspected:
                resource = inspected["item"]
                values = dict(
                    kind=kind,
                    identifier=identifier,
                    header_digest=resource["header_digest"],
                    payload_digest=resource["payload_digest"],
                    clearance=resource["clearance"],
                    watermark=inspected["watermark"],
                )
        return {
            **values,
            "action": action,
            "reason": "إجراء اصطناعي صريح للمشتق وحده",
            "request_key": str(uuid.uuid4()),
            "parameters": {"query": "عبارة محددة"}
            if action == "REBUILD" and kind == "AI_CANDIDATES"
            else {},
            **changes,
        }

    def plan(self, action="CLEAR", kind="SEARCH_INDEX", **changes):
        with services.preview(
            proposal=self.proposal(action, kind, **changes), **self.base
        ) as value:
            return value

    def change(self, action="CLEAR", kind="SEARCH_INDEX", **changes):
        with services.apply(
            plan=self.plan(action, kind, **changes), confirmed=True, **self.base
        ) as value:
            return value
