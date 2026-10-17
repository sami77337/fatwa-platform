"""E6 integration boundary. No placeholder service or synthetic-success fallback."""
from dataclasses import dataclass


class WorkflowIntegrationPending(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkflowScenario:
    """Prepared outside HTTP by actual E1/E2/E3 services, then read by the browser.

    Values are real persisted UUIDs/GET paths/selectors/expected synthetic text.
    No arbitrary callable, source map, path, or private input comes from the UI.
    """
    worklist_path: str
    batch_ids: tuple[str, str]
    repeated_external_id: str
    detail_paths: tuple[str, str]
    original_questions: tuple[str, str]
    blocked_detail_path: str
    reviewed_detail_path: str


def prepare_workflow_scenario() -> WorkflowScenario:
    # Replaced only after reading actual producer services and E4 routes/hooks.
    # Baseline guard/storage/browser tests do not claim this workflow is ready.
    raise WorkflowIntegrationPending("E1_E2_E3_E4_ACTUAL_SERVICES_AND_GET_HOOKS_PENDING")
