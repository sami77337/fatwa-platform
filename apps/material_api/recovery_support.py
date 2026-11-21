"""Fresh-process actual API reads over restored originals; no new table owner."""

from dataclasses import replace
from hashlib import sha256

from django.test import Client, override_settings

from apps.research_library import recovery_support as library_recovery
from apps.research_library.test_support import video

from .test_support import BASE, FEATURES

TABLES = ()
FUNCTIONS = ()
TRIGGERS = ()


def populate():
    return library_recovery.populate()


def verify_restored(pins):
    row = pins["versions"]["video"]
    url = BASE + row["public_id"] + "/versions/" + str(row["number"]) + "/"
    before = library_recovery._row_pins(pins["case"]["case_id"])
    denied = {}
    with library_recovery._fixture(pins["case"]) as common, override_settings(
        FATWA_MATERIAL_API_ENABLED=True, MIDDLEWARE=FEATURES["MIDDLEWARE"]
    ):
        client = Client(REMOTE_ADDR="127.0.0.1", HTTP_HOST="127.0.0.1")
        def available():
            response = client.get(url)
            assert response.status_code == 200
            actual = response.json()["material"]
            assert actual["version_sha256"] == row["digest"]
            assert actual["material_id"] == row["public_id"]
            original = client.get(url + "original/")
            assert original.status_code == 200 and original.content == video()
            assert original["X-Content-SHA256"] == sha256(video()).hexdigest()
        def refusal(kind):
            response = client.get(url)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "unavailable"
            denied[kind] = denied.get(kind, 0) + 1
        available()
        for kind, name, value in (
            ("disabled_api", "FATWA_MATERIAL_API_ENABLED", False),
            ("missing_authority", "FATWA_RESEARCH_LIBRARY_AUTHORITY", None),
            ("missing_identity_provider", "FATWA_CASEWORK_IDENTITY_PROVIDER", None),
        ):
            with override_settings(**{name: value}):
                refusal(kind)
        directory = common["provider"]
        old = directory.identities["publisher"]
        try:
            directory.identities["publisher"] = replace(old, active=False)
            refusal("revoked_release_actor")
        finally:
            directory.identities["publisher"] = old
        available()
    assert library_recovery._row_pins(pins["case"]["case_id"]) == before == pins["tables"]
    assert library_recovery._canonical(pins["case"]["case_id"]) == pins["case"]["canonical_sha256"]
    return {"status": "PASS", "new_table_count": 0, "exact_public_original": True,
            "denial_checks": denied, "denied_read_count": sum(denied.values()),
            "positive_reads_after_denial": True, "canonical_and_history_unchanged": True}
