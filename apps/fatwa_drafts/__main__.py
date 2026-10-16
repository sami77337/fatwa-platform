"""Run a deterministic synthetic demo: python -m apps.fatwa_drafts."""

from .domain import HumanMetadata, SyntheticStage
from .intake import IntakeItem, serialize_intake


def main() -> None:
    human: HumanMetadata = {"human_editor": "محرر تجريبي", "editorial_note": "بيانات اصطناعية فقط"}
    stage = SyntheticStage(synthetic_fixtures_only=True)
    sample = IntakeItem(
        "SYNTHETIC-001",
        "سؤال تجريبي لا يمثل حالة حقيقية؟",
        "https://example.invalid/finished-demo.mp4",
    )
    stage.ingest(serialize_intake((sample,)), **human)
    stage.move(sample.external_id, "draft_preparation", expected_revision=1, **human)
    stage.edit(
        sample.external_id,
        expected_revision=2,
        title="عنوان تجريبي",
        answer="نص اختبار أدخله محرر بشري؛ ليس إجابة شرعية.",
        reviewer_notes="",
        **human,
    )
    stage.move(sample.external_id, "ready_for_future_review", expected_revision=3, **human)
    print(stage.preview().decode("utf-8"))


if __name__ == "__main__":
    main()
