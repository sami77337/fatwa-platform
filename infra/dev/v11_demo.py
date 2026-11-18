"""Manual V11 synthetic pilot on the existing disposable V9/V10 runtime.

Run via with_casework_postgres.py. This module accepts no keys or authority
payloads. Its ephemeral TEST fixture only operates after explicit human actions
in the existing UI. Restarting discards credentials, worker memory and all data.
"""

import argparse
import json
import re
import tempfile
from html import unescape
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from infra.dev import v9_demo, v10_demo


def _authorities(scope, directory):
    """Pin exact seeded identities, epochs, cases and catalog source versions."""
    from django.utils import timezone

    from apps.pilot_workbench.fixtures import FixtureOperatorAuthority
    from apps.reference.models import ReferenceHeading
    from apps.source_rights import services as rights
    from apps.source_rights.authority import SourceRightsAuthority

    epochs = {
        subject: directory.resolve(subject).auth_epoch
        for subject in ("demo-mufti", "demo-publisher")
    }
    source_hashes = frozenset(
        rights._digest(rights._reference(heading_id)[0])
        for heading_id in ReferenceHeading.objects.values_list("pk", flat=True)
    )
    if len(scope) != 1 or len(source_hashes) != 2:
        raise RuntimeError(
            "V11 requires exactly one seeded case and two synthetic source positions"
        )

    def current(provider_id, subject_id, auth_epoch, case_ref):
        actor = directory.resolve(subject_id)
        return bool(
            provider_id == directory.provider_id
            and subject_id in epochs
            and auth_epoch == epochs[subject_id]
            and actor
            and actor.auth_epoch == auth_epoch
            and actor.active
            and actor.role == "MUFTI"
            and actor.valid_until > timezone.now()
            and case_ref in scope
            and case_ref in actor.case_keys
        )

    class Rights(SourceRightsAuthority):
        def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action, source_sha256):
            actions = {
                "demo-mufti": frozenset({"VIEW", "REGISTER", "PROPOSE"}),
                "demo-publisher": frozenset({"VIEW", "APPROVE", "REJECT", "REVOKE"}),
            }
            return bool(
                current(provider_id, subject_id, auth_epoch, case_ref)
                and action in actions.get(subject_id, ())
                and ((action == "VIEW" and source_sha256 == "") or source_sha256 in source_hashes)
            )

    class Operator(FixtureOperatorAuthority):
        def permits(self, *, provider_id, subject_id, auth_epoch, case_ref, action):
            return bool(
                subject_id == "demo-mufti"
                and current(provider_id, subject_id, auth_epoch, case_ref)
                and action in {"OPEN", "AUTHORIZE_RETURN", "REPORT_PROVIDER"}
            )

    return Rights(), Operator()


def _notice(_arguments):
    print("V11 ACTIVE: temporary, human-operated LOCAL delivery fixture; no external sender.")
    print("Use /casework/staff/login/ in separate Mufti and publisher browser sessions.")
    print("Mufti: review held source event, register exact source, propose synthetic rights.")
    print("Publisher: independently review rights; then Mufti can research and cite that position.")
    print("Mufti: compose multipart answer, review and approve, explicitly release privately.")
    print("Local pilot: separately confirm return permission, then report each part manually.")
    print("Provider ACCEPTED/DELIVERED/FAILED are local fixture reports, never requester reading.")
    print(
        "Publisher: independently approve edited publication; authenticated library remains available."
    )
    print("Anonymous library preview stays closed. Research media grants are not configured.")
    print(
        "Fixture expires after 30 minutes; no automatic retry/resend/recovery or authority renewal."
    )
    print(
        "Stopping destroys the temporary database, private originals, credentials and fixture keys."
    )
    print("Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.", flush=True)


def _smoke(receipt, output, held, control_root):
    """Exercise startup/CSRF and freeze denial; never synthesize domain approvals."""
    from django.conf import settings
    from django.test import Client

    from apps.casework.models import AnswerRevision, CaseDecision
    from apps.delivery_queue.models import DeliveryIntent
    from apps.pilot_workbench import services as pilot
    from apps.platform_recovery import maintenance
    from apps.platform_recovery.integration import MaintenanceUnavailable
    from apps.source_rights.models import RightsAction, RightsRevision, SourceRegistration

    def require(condition, label):
        if not condition:
            raise RuntimeError("V11 startup smoke failed: " + label)

    def client():
        return Client(enforce_csrf_checks=True, REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")

    def post(browser, path, page, fields):
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
        require(token, "CSRF form")
        return browser.post(
            path,
            urlencode({"csrfmiddlewaretoken": unescape(token[1]), **fields}),
            content_type="application/x-www-form-urlencoded",
        )

    v10_demo._check_source_desk(receipt, output, held)
    requester = client()
    page = requester.get("/casework/status/")
    require(
        post(
            requester, "/casework/status/", page, {"action": "unlock", "token": receipt["token"]}
        ).status_code
        == 303,
        "requester unlock",
    )
    require(requester.get("/casework/status/").status_code == 200, "requester portal")
    for subject in ("demo-mufti", "demo-publisher"):
        staff = client()
        credential = next(
            line.split(": ", 1)[1]
            for line in output.splitlines()
            if line.startswith(subject + " temporary credential: ")
        )
        login = staff.get("/casework/staff/login/")
        require(
            post(staff, "/casework/staff/login/", login, {"credential": credential}).status_code
            == 303,
            subject + " login",
        )
        desk = staff.get("/casework/staff/")
        for action, extra in (
            ("rights_desk", {"case_ref": receipt["public_ref"], "query": "", "edition_id": ""}),
            ("research_open", {"case_ref": receipt["public_ref"]}),
            ("pub_library", {"query": ""}),
        ):
            response = post(
                staff,
                "/casework/staff/",
                desk,
                {"action": action, **extra},
            )
            require(response.status_code == 200, subject + " " + action)
        denied = post(
            staff,
            "/casework/staff/",
            desk,
            {"action": "pilot_open", "case_ref": receipt["public_ref"]},
        )
        if subject == "demo-mufti":
            require(
                denied.status_code == 200
                and "يلزم اعتماد بشري حالي" in denied.content.decode()
                and 'value="pilot_authorize"' not in denied.content.decode(),
                "pilot read-only until canonical human approval",
            )
        else:
            require(denied.status_code == 409, "publisher has no pilot operator authority")

    directory = settings.FATWA_CASEWORK_IDENTITY_PROVIDER
    rights = settings.FATWA_SOURCE_RIGHTS_AUTHORITY
    mufti = directory.resolve("demo-mufti")
    require(
        not rights.permits(
            provider_id=directory.provider_id,
            subject_id=mufti.subject_id,
            auth_epoch=mufti.auth_epoch,
            case_ref=receipt["public_ref"],
            action="APPROVE",
            source_sha256="0" * 64,
        ),
        "no implicit rights approval",
    )
    require(
        settings.FATWA_RESEARCH_WORKSPACE_RIGHTS.media_rights is None, "no research media grant"
    )
    require(settings.FATWA_LIBRARY_PREVIEW_POLICY is None, "anonymous preview closed")
    for model in (
        AnswerRevision,
        CaseDecision,
        DeliveryIntent,
        SourceRegistration,
        RightsRevision,
        RightsAction,
    ):
        require(not model.objects.exists(), "no automatic " + model.__name__)

    frozen = maintenance.enter(root=control_root, synthetic_fixtures_only=True)
    require(frozen["phase"] == "FROZEN", "maintenance drain")
    require(requester.get("/casework/status/").status_code == 503, "HTTP frozen denial")
    try:
        pilot.read_workbench(
            case_id=receipt["case_id"],
            subject_id=mufti.subject_id,
            provider=directory,
            synthetic_fixtures_only=True,
        )
    except MaintenanceUnavailable:
        pass
    else:
        raise RuntimeError("V11 frozen direct service unexpectedly admitted")
    # This explicit smoke-only resume follows the verified denial; interactive startup never freezes.
    maintenance.resume(
        root=control_root,
        expected_generation=frozen["generation"],
        confirmed=True,
        synthetic_fixtures_only=True,
    )
    require(requester.get("/casework/status/").status_code == 200, "HTTP after explicit resume")
    print(
        json.dumps(
            {
                "v11_startup": "PASS",
                "maintenance_active_frozen_resume": "PASS",
                "scoped_staff_and_requester_sessions": "PASS",
                "automatic_domain_approvals": False,
                "anonymous_preview_granted": False,
                "external_send": False,
            },
            sort_keys=True,
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Check startup and maintenance; no server or approvals.",
    )
    arguments = parser.parse_args(argv)
    original_configure = v9_demo._configure
    held = None

    with tempfile.TemporaryDirectory(prefix="fatwa-v11-control-", dir="/tmp") as control:
        control_root = Path(control)

        def configure(scope, **options):
            nonlocal held
            from django.conf import settings

            from apps.pilot_workbench.fixtures import setup_synthetic_fixture
            from apps.platform_recovery import maintenance
            from apps.platform_recovery.integration import mutation_scope
            from apps.research_workspace.source_rights_adapter import SourceRightsAdapter

            original_configure(scope, **options)
            settings.FATWA_MUFTI_WORKSPACE_ENABLED = True
            settings.FATWA_REQUESTER_PORTAL_ENABLED = True
            settings.FATWA_SOURCE_CASE_INTAKE_DESK_ENABLED = True
            settings.FATWA_SOURCE_CASE_INTAKE_SIMULATOR_ENABLED = True
            directory = v10_demo._source_reviewer(settings.FATWA_CASEWORK_IDENTITY_PROVIDER)
            settings.FATWA_CASEWORK_IDENTITY_PROVIDER = directory
            rights, operator = _authorities(scope, directory)
            settings.FATWA_SOURCE_RIGHTS_ENABLED = True
            settings.FATWA_SOURCE_RIGHTS_AUTHORITY = rights
            settings.FATWA_SOURCE_RIGHTS_ENFORCED = True
            settings.FATWA_RESEARCH_WORKSPACE_ENABLED = True
            settings.FATWA_RESEARCH_WORKSPACE_RIGHTS = SourceRightsAdapter()
            settings.FATWA_LIBRARY_PREVIEW_ENABLED = False
            settings.FATWA_LIBRARY_PREVIEW_POLICY = None
            if settings.MIDDLEWARE[0] != "apps.platform_recovery.middleware.MaintenanceGuard":
                raise RuntimeError("V11 requires the integrated topmost maintenance middleware")
            maintenance.initialize(
                root=control_root,
                storage=settings.FATWA_PRIVATE_MEDIA_STORAGE,
                synthetic_fixtures_only=True,
            )
            settings.FATWA_RECOVERY_MAINTENANCE_ROOT = str(control_root)
            settings.FATWA_RECOVERY_MAINTENANCE_REQUIRED = True
            settings.FATWA_RECOVERY_ENCRYPTION_REQUIRED = True
            settings.FATWA_RECOVERY_V10_TEST_COMPAT = False
            fixture = setup_synthetic_fixture(
                operator_authority=operator,
                identity_provider=directory,
                synthetic_fixtures_only=True,
            )
            for key, value in fixture.settings().items():
                setattr(settings, key, value)
            with mutation_scope():
                held = v10_demo._held_source_event()

        def check(receipt, output, source_raw, storage):
            _smoke(receipt, output, held, control_root)

        with (
            patch.object(v9_demo, "_configure", configure),
            patch.object(v9_demo, "_smoke", check),
            patch.object(v9_demo, "_startup_notice", _notice),
        ):
            v9_demo.main(["--smoke"] if arguments.smoke else [])


if __name__ == "__main__":
    main()
