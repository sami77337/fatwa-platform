"""Positive and fail-closed B6 orchestration checks, not app acceptance."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("b6qa", Path(__file__).resolve().parents[2] / "tools/dev/qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


class QATests(unittest.TestCase):
    def test_local_transports(self):
        for endpoint in ["unix:///var/run/docker.sock", "npipe:////./pipe/dockerDesktopLinuxEngine"]:
            self.assertEqual(qa.docker_transport(endpoint), endpoint)

    def test_remote_and_injected_transports_rejected(self):
        for endpoint in ["tcp://127.0.0.1:2375", "ssh://host", "unix:///a\n--host=x", ""]:
            with self.assertRaises(RuntimeError):
                qa.docker_transport(endpoint)

    def test_inherited_credentials_removed(self):
        with patch.dict(os.environ, {"PGPASSWORD": "private", "PGSERVICE": "live",
                                    "DJANGO_SECRET_KEY": "private", "DOCKER_HOST": "tcp://host",
                                    "DATABASE_URL": "private", "OTHER_TOKEN": "private"}):
            env = qa.environment()
        for key in ["PGPASSWORD", "PGSERVICE", "DJANGO_SECRET_KEY", "DOCKER_HOST", "DATABASE_URL", "OTHER_TOKEN"]:
            self.assertNotIn(key, env)
        self.assertEqual(env["PGPORT"], "1")

    def test_ci_rejects_dirty_checkout(self):
        from types import SimpleNamespace
        with patch.dict(os.environ, {"CI": "true"}), patch.object(qa, "run", side_effect=[
            SimpleNamespace(stdout="a" * 40), SimpleNamespace(stdout=" M apps/reference/views.py")
        ]):
            with self.assertRaises(RuntimeError):
                qa.committed()

    def test_clean_checkout_identified(self):
        from types import SimpleNamespace
        with patch.object(qa, "run", side_effect=[SimpleNamespace(stdout="a" * 40), SimpleNamespace(stdout="")]):
            self.assertEqual(qa.committed()["working_tree"], "CLEAN")

    def test_shell_is_never_used_with_spaced_paths(self):
        with patch.object(qa.subprocess, "run") as execute:
            qa.run(["C:/Program Files/Python/python.exe", "a&b.py"])
        self.assertFalse(execute.call_args.kwargs["shell"])
        self.assertEqual(execute.call_args.args[0][1], "a&b.py")

    def test_wrong_postgres_version_fails_before_docker(self):
        with patch.object(qa, "run") as execute, self.assertRaises(RuntimeError):
            qa.postgres(16)
        execute.assert_not_called()

    def test_ephemeral_topology_and_real_app_commands(self):
        from types import SimpleNamespace
        calls = []
        def execute(args, **kwargs):
            calls.append(args)
            value = "unix:///var/run/docker.sock" if args[1:3] == ["context", "inspect"] else ""
            if "{{.State.ExitCode}}" in args:
                value = "0"
            return SimpleNamespace(stdout=value)
        with patch.dict(os.environ, {}, clear=True), patch.object(qa, "run", side_effect=execute):
            qa.postgres(18)
        flattened = [arg for call in calls for arg in call]
        self.assertNotIn("--publish", flattened)
        self.assertNotIn("-p", flattened)
        self.assertNotIn("--volume", flattened)
        self.assertNotIn("fatwa_reference", flattened)
        self.assertIn("--internal", flattened)
        self.assertIn("PGDATA=/var/lib/postgresql/data", flattened)
        self.assertIn("tools/dev/qa_worker.py", flattened)
        build_index = next(i for i, call in enumerate(calls) if "build" in call)
        network_index = next(i for i, call in enumerate(calls) if "network" in call and "create" in call)
        self.assertLess(build_index, network_index)

    def test_unavailable_docker_never_builds_or_mutates(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(qa, "run", side_effect=FileNotFoundError) as execute:
            with self.assertRaises(qa.DockerUnavailable):
                qa.postgres(17)
        self.assertEqual(execute.call_count, 1)

    def test_pg17_covers_image_volume_with_tmpfs(self):
        from types import SimpleNamespace
        calls = []
        def execute(args, **kwargs):
            calls.append(args)
            value = "0" if "{{.State.ExitCode}}" in args else ""
            return SimpleNamespace(stdout=value)
        with patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock"}, clear=True), patch.object(qa, "run", side_effect=execute):
            qa.postgres(17)
        db_run = next(call for call in calls if "postgres:17-bookworm" in call)
        self.assertIn("/var/lib/postgresql/data:rw,nosuid,nodev,size=1073741824", db_run)
