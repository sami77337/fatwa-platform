"""Access-review contracts through the combined requester/team dispatcher."""

from django.test import override_settings

from apps.requester_access_review import tests as contracts
from tests.casework.test_http import post


@override_settings(ROOT_URLCONF="config.campaign_urls")
class CampaignAccessTests(contracts.AccessReviewTests):
    def login(self, *refs):
        team = super().login(*refs)
        self.assertContains(team, "مساحة الشيخ والفريق")
        self.assertContains(team, "طلبات مراجعة الوصول")
        return post(self.staff, contracts.STAFF, {"action": "access_queue"}, team)

    def test_review_queue_opens_current_team_editor_and_returns_to_queue(self):
        case, _ = self.intake()
        self.assertEqual(self.request_help().status_code, 303)
        queue = self.login(case.public_ref)
        team = post(
            self.staff, contracts.STAFF, {"action": "open", "case_ref": case.public_ref}, queue
        )
        self.assertContains(team, 'id="queue-state"')
        self.assertContains(team, 'id="answer-text"')
        self.assertContains(team, case.source.original_question)
        queue = post(self.staff, contracts.STAFF, {"action": "access_queue"}, team)
        self.assertContains(queue, "بدء متابعة التحقق")
        self.assertNotContains(queue, case.source.original_question)
