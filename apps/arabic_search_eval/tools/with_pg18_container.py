import json
import os
import subprocess
import sys
import time
import uuid

name = "v14-search-" + uuid.uuid4().hex[:8]
image = "postgres@sha256:2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc"
env = os.environ.copy()
for key in ("DATABASE_URL", "PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGPASSFILE", "PGOPTIONS"):
    env.pop(key, None)
try:
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::5432",
            "-e",
            "POSTGRES_USER=wave7_synthetic",
            "-e",
            "POSTGRES_DB=wave7_synthetic_v6local",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    for i in range(100):
        ready = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "wave7_synthetic",
                "-d",
                "wave7_synthetic_v6local",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            break
        time.sleep(0.1)
    port = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]["NetworkSettings"][
        "Ports"
    ]["5432/tcp"][0]["HostPort"]
    version = subprocess.check_output(
        ["docker", "exec", name, "postgres", "--version"], text=True
    ).strip()
    print("SYNTHETIC_POSTGRES=" + version + "; isolated disposable loopback Docker", flush=True)
    env.update(
        FATWA_PRODUCTION="0",
        FATWA_WAVE7_SYNTHETIC_WRITES="1",
        DJANGO_SETTINGS_MODULE="config.settings.campaign_review",
        PGHOST="127.0.0.1",
        PGPORT=port,
        PGUSER="wave7_synthetic",
        PGPASSWORD="",
        PGDATABASE="wave7_synthetic_v6local",
        PGTESTDATABASE="test_wave7_synthetic_v6local",
        PG_EXPECTED_MAJOR="18",
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import django; django.setup(); from apps.intake_workflow.guards import initialize_synthetic_database; initialize_synthetic_database(synthetic_fixtures_only=True); from django.core.management import call_command; call_command('migrate',interactive=False,verbosity=0)",
        ],
        env=env,
        check=True,
    )
    sys.exit(subprocess.run([sys.executable, "manage.py", *sys.argv[1:]], env=env).returncode)
finally:
    subprocess.run(
        ["docker", "rm", "-fv", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
