"""Actual subprocess CLI and Django requests; no database access permitted."""

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings

from apps.fast9_case_policy_join import services

KEY = "batch-synthetic-csv-1"
PARAMS = dict(
    case_key=KEY, actor="MUFTI", action="synthetic::answer.create", resource="synthetic::answer"
)


@override_settings(ROOT_URLCONF="apps.fast9_case_policy_join.urls")
class HttpTests(SimpleTestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("apps.fast9_case_policy_join.views"), "Guarded API is missing"
        )
        env = patch.dict(os.environ, FATWA_PRODUCTION="0", FATWA_FAST9_CASE_POLICY_JOIN="1")
        env.start()
        self.addCleanup(env.stop)

    def get(self, path="/select", params=None, **extra):
        return self.client.get(path, params or PARAMS, HTTP_HOST="localhost", **extra)

    def test_real_select_then_evaluate_returns_only_deny_and_no_cache(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        result = response.json()
        self.assertEqual(result["effect"], "DENY")
        self.assertIs(result["allowed"], False)
        response = self.get("/evaluate", PARAMS | {"receipt": json.dumps(result["receipt"])})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synthetic_context"], "VERIFIED")
        self.assertEqual(response.json()["owner_policy_connection"], "NOT_CONNECTED")
        head = self.client.head("/select", PARAMS, HTTP_HOST="localhost")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")

    def test_default_off_production_and_nonloopback_fail_before_source_access(self):
        with patch.object(
            services, "select_evidence", side_effect=AssertionError("source touched")
        ):
            for env in ({"FATWA_FAST9_CASE_POLICY_JOIN": "0"}, {"FATWA_PRODUCTION": "1"}):
                with patch.dict(os.environ, env):
                    self.assertEqual(self.get().status_code, 404)
            self.assertEqual(self.get(REMOTE_ADDR="192.0.2.8").status_code, 404)
            self.assertEqual(
                self.client.get("/select", PARAMS, HTTP_HOST="testserver").status_code, 404
            )
            with override_settings(FATWA_PRODUCTION=True):
                self.assertEqual(self.get().status_code, 404)

    def test_write_verbs_are_rejected_before_any_source_or_mutation(self):
        with patch.object(
            services, "select_evidence", side_effect=AssertionError("source touched")
        ):
            for method in ("post", "put", "patch", "delete", "options", "trace"):
                response = getattr(self.client, method)("/select", HTTP_HOST="localhost")
                self.assertEqual(response.status_code, 405)

    def test_duplicate_unknown_and_malicious_parameters_never_echo(self):
        for query in (
            "case_key=history&case_key=history",
            "secret=DO_NOT_ECHO",
            "actor=%00",
            "actor=%EF%BC%ADUFTI",
        ):
            response = self.client.get("/evaluate?" + query, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(b"DO_NOT_ECHO", response.content)
            self.assertIs(response.json()["allowed"], False)
        with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1):
            self.assertEqual(self.get().status_code, 400)

    def test_shared_query_limit_and_standalone_adapter_limit_both_reject(self):
        query = "/evaluate?receipt=" + "x" * 17000
        response = self.client.get(query, HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_query"})
        with override_settings(MIDDLEWARE=[]):
            self.client = Client()
            response = self.get("/evaluate", PARAMS | {"receipt": "x" * 16385})
            self.assertEqual(response.status_code, 400)
            self.assertIs(response.json()["allowed"], False)
            response = self.client.get("/evaluate?" + "x" * 52000, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 400)

    @override_settings(MIDDLEWARE=[])
    def test_standalone_adapter_also_blocks_write_verbs(self):
        self.test_write_verbs_are_rejected_before_any_source_or_mutation()

    def test_cross_case_full_receipt_substitution_is_rejected(self):
        receipt = services.select_evidence(**(PARAMS | {"case_key": "history"}))
        response = self.get("/evaluate", PARAMS | {"receipt": json.dumps(asdict(receipt))})
        self.assertEqual(response.status_code, 400)
        self.assertIn("CROSS_CASE_SUBSTITUTION", response.json()["reason_codes"])
        self.assertIsNone(response.json()["receipt"])

    def test_unjoined_workflow_is_503_and_not_a_verified_policy(self):
        response = self.get(
            params=PARAMS | {"action": "start_review", "resource": "workflow::UNREVIEWED"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["synthetic_context"], "NOT_CONNECTED")


class CliTests(SimpleTestCase):
    def run_cli(self, *args, data=None, env=None):
        return subprocess.run(
            [sys.executable, "-B", "-m", "tools.fast9_case_policy_join", *args],
            input=data,
            capture_output=True,
            env=os.environ | {"FATWA_PRODUCTION": "0"} | (env or {}),
            timeout=30,
        )

    def args(self, command):
        return (
            "--synthetic-only",
            command,
            "--case-key",
            KEY,
            "--actor",
            "MUFTI",
            "--action",
            "synthetic::answer.create",
            "--resource",
            "synthetic::answer",
        )

    def test_cli_roundtrip_uses_stdin_receipt_and_never_authorizes(self):
        selected = self.run_cli(*self.args("select"))
        self.assertEqual(selected.returncode, 0, selected.stderr.decode())
        data = json.loads(selected.stdout)
        self.assertIs(data["allowed"], False)
        evaluated = self.run_cli(
            *self.args("evaluate"), "--receipt-stdin", data=json.dumps(data["receipt"]).encode()
        )
        self.assertEqual(evaluated.returncode, 0, evaluated.stderr.decode())
        result = json.loads(evaluated.stdout)
        self.assertEqual(result["synthetic_context"], "VERIFIED")
        self.assertEqual(result["effect"], "DENY")
        self.assertIs(result["allowed"], False)

    def test_cli_requires_opt_in_and_refuses_production_and_ambiguous_flags(self):
        for args, env in (
            (self.args("select")[1:], {}),
            (self.args("select"), {"FATWA_PRODUCTION": "1"}),
            ((*self.args("select"), "--actor", "ORGANIZER"), {}),
            ((*self.args("select"), "--policy-file", "secret-location"), {}),
        ):
            result = self.run_cli(*args, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"secret-location", result.stdout + result.stderr)

    def test_cli_bounds_stdin_and_rejects_bad_utf8_and_extra_grants(self):
        receipt = asdict(services.select_evidence(**PARAMS))
        for data in (b"\xff", b"x" * 16385, json.dumps(receipt | {"allowed": True}).encode()):
            result = self.run_cli(*self.args("evaluate"), "--receipt-stdin", data=data)
            self.assertEqual(result.returncode, 3, result.stderr.decode())
            self.assertEqual(json.loads(result.stdout)["synthetic_context"], "REJECTED")
            self.assertIs(json.loads(result.stdout)["allowed"], False)
