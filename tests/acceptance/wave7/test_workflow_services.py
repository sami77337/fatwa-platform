"""Required actual-producer gate, separate from the frozen-foundation probe suite."""
import json
from pathlib import Path
import subprocess
import sys

from django.test import TransactionTestCase
from .target import require_lane_configuration
from .workflow_contract import prepare_workflow_scenario

require_lane_configuration()


class ProducerWorkflowTests(TransactionTestCase):
    def test_intake_replay_conflict_reference_and_review_survive_process_restart(self):
        scenario = prepare_workflow_scenario(require_get_registration=False)
        reports = []
        for key in scenario.batch_keys:
            replay = subprocess.run([sys.executable, str(Path(__file__).with_name("workflow_process.py")),
                "replay", "--key", key], capture_output=True, text=True, timeout=30)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(json.loads(replay.stdout)["decision"], "REPLAY")
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("workflow_process.py")),
                "inspect", "--key", key], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            reports.append(json.loads(result.stdout))  # source strings are not decoded/rewritten
        self.assertEqual(tuple(report["batch_id"] for report in reports), scenario.batch_ids)
        self.assertEqual([report["event_count"] for report in reports], [4, 0])
        self.assertEqual([len(report["items"]) for report in reports], [8, 8])
        self.assertEqual([report["items"][6]["question_original"] for report in reports], list(scenario.original_questions))
        self.assertEqual(reports[0]["items"][6]["review_status"], "REVIEWED_INTERNAL")
        self.assertEqual(reports[1]["items"][6]["review_status"], "UNREVIEWED")
        self.assertEqual(scenario.verified_reference.batch_id, scenario.batch_ids[0])
        self.assertEqual(scenario.verified_reference.reference_ordinal, 1)
        self.assertIn("، ج الأول، ص 8 ", scenario.verified_reference.citation_text)

    def test_two_new_review_processes_have_one_winner_and_one_conflict(self):
        scenario = prepare_workflow_scenario(require_get_registration=False)
        command = [sys.executable, str(Path(__file__).with_name("workflow_process.py")),
                   "start-review", "--item", scenario.review_target_id]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(2)]
        outputs = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertIn(process.returncode, [0, 3], stderr)
                outputs.append((process.returncode, json.loads(stdout)))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
        self.assertCountEqual([code for code, _ in outputs], [0, 3])
        self.assertEqual(next(result for code, result in outputs if code == 3),
                         {"code":"REVIEW_CONFLICT", "status_code":409})
        from apps.intake_workflow.models import IntakeItem, ReviewEvent
        self.assertEqual(IntakeItem.objects.get(pk=scenario.review_target_id).review_status, "IN_REVIEW")
        self.assertEqual(ReviewEvent.objects.filter(intake_item_id=scenario.review_target_id).count(), 1)
