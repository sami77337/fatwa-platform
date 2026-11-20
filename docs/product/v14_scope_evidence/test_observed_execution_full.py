import copy
import json
import unittest
from pathlib import Path

try:
    from .verify_observed_execution_full import EvidenceError, verify
except ImportError:
    from verify_observed_execution_full import EvidenceError, git_blob, verify

HERE = Path(__file__).resolve().parent
BASE = "6b4f77e29ccb1f21d48ad3d77f5e63d3be953fab"


class FullObservedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((HERE / "observed_execution_full.json").read_text(encoding="utf-8"))
        cls.candidate = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
        cls.files = {}
        refs = []
        for group in cls.data["groups"]:
            refs.extend(group["code"])
            refs.extend(group["tests"])
        for ref in refs:
            cls.files[ref["path"]] = ref["blob_sha"]

    def read_file(self, path):
        import subprocess
        return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=HERE.parents[2])

    def check(self, mutate=None, read_file=None):
        data = copy.deepcopy(self.data)
        if mutate:
            mutate(data)
        return verify(data, self.candidate, read_file or self.read_file)

    def reject(self, mutate):
        with self.assertRaises(EvidenceError):
            self.check(mutate)

    def test_all_five_groups_and_22_points_remain_bounded(self):
        out = self.check()
        self.assertEqual(out["groups"], 5)
        self.assertEqual(out["unique_owner_points"], 22)
        self.assertEqual(out["named_test_methods"], 20)
        self.assertEqual(out["status_upgrades"], 0)
        self.assertEqual(out["acceptance"], "HOLD")

    def test_changed_original_wording_or_status_is_rejected(self):
        self.reject(lambda d: d["groups"][0]["points"][0].update(original_text="rewritten"))
        self.reject(lambda d: d["groups"][0]["points"][0].update(preserved_status="COMPLETE"))

    def test_missing_or_duplicate_group_and_point_are_rejected(self):
        self.reject(lambda d: d["groups"].pop())
        self.reject(lambda d: d["groups"][1].update(id="recording-controls"))
        self.reject(lambda d: d["groups"][1]["points"][0].update(id=70))

    def test_changed_source_blob_or_missing_file_is_rejected(self):
        self.reject(lambda d: d["groups"][0]["code"][0].update(blob_sha="0" * 40))
        self.reject(lambda d: d["groups"][0]["tests"][0].update(path="../outside.py"))

    def test_wrong_test_kind_or_method_is_rejected(self):
        self.reject(lambda d: d["groups"][0]["tests"][0].update(kind="negative"))
        self.reject(lambda d: d["groups"][0]["tests"][0].update(symbol="x.y.z"))

    def test_wrong_postgres_job_or_head_is_rejected(self):
        self.reject(lambda d: d["jobs"][0].update(job_id=135008890057))
        self.reject(lambda d: d["jobs"][1].update(tested_sha="f" * 40))
        self.reject(lambda d: d["jobs"].pop())

    def test_status_promotion_or_percentage_invention_is_rejected(self):
        self.reject(lambda d: d.update(status_upgrades=1))
        self.reject(lambda d: d.update(percentage=85))
        self.reject(lambda d: d.update(acceptance="PASSED"))

    def test_historical_startup_and_pdf_limits_cannot_be_erased(self):
        self.reject(lambda d: d.update(limits=["All verified", "All accepted"]))

    def test_mutated_git_blob_bytes_are_rejected(self):
        def wrong(path):
            return b"tampered"
        with self.assertRaises(EvidenceError):
            self.check(read_file=wrong)


if __name__ == "__main__":
    unittest.main()
