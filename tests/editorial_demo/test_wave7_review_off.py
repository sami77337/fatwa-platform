"""No-DB default-off boundary; use ordinary test settings, never DB labels here."""
from unittest.mock import patch
from io import StringIO
from uuid import uuid4
from django.core.management import get_commands
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.urls import resolve, Resolver404
from apps.editorial_demo import views


class Wave7DefaultOffTests(SimpleTestCase):
    def test_persisted_route_and_cli_absent_from_default_settings(self):
        # The old generic preview route catches this segment as an unknown ID;
        # the separate persisted route must not be registered in default settings.
        self.assertNotEqual(resolve('/dev/editorial-preview/persisted').url_name, 'wave7_editorial_review')
        self.assertNotIn('wave7_review', get_commands())

    def test_direct_view_is_default_off_before_queries(self):
        request = RequestFactory().get('/dev/editorial-preview/persisted', HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
        response = views.persisted_review(request)
        self.assertEqual(response.status_code, 404)

    def test_unsafe_methods_reject_before_feature_or_database_processing(self):
        for method in ('post', 'put', 'patch', 'delete'):
            request = getattr(RequestFactory(), method)('/dev/editorial-preview/persisted', HTTP_HOST='localhost')
            self.assertEqual(views.persisted_review(request).status_code, 405)

    def test_legacy_worklist_is_unchanged(self):
        response = self.client.get('/dev/editorial-preview/pipeline', HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'SYN-P01')
        self.assertNotContains(response, 'wave7-persisted')

    def test_cli_parser_and_missing_ack_fail_before_transaction_without_database(self):
        from django.core.management import CommandError
        from apps.intake_workflow import guards
        from apps.intake_workflow.management.commands.wave7_review import Command
        command = Command(stdout=StringIO(), stderr=StringIO())
        arguments = ['--item', str(uuid4()), '--operation', str(uuid4()), '--action', 'start_review',
                     '--expected-status', 'UNREVIEWED', '--reason', 'DO_NOT_ECHO']
        parser = command.create_parser('manage.py', 'wave7_review')
        with self.assertRaises(CommandError):
            parser.parse_args(arguments)
        options = vars(parser.parse_args(['transition', *arguments]))
        with patch.object(guards.transaction,'atomic') as atomic, self.assertRaises(CommandError) as caught:
            command.handle(**options)
        atomic.assert_not_called()
        self.assertEqual(str(caught.exception), 'SYNTHETIC_ACK_REQUIRED')

    def test_service_rejects_illegal_actions_and_reasons_without_database(self):
        from apps.intake_workflow import contracts as c
        from apps.intake_workflow.review import transition_review
        for action, reason in (('approve','Synthetic'),('publish','Synthetic'),('start_review',' '),
                               ('start_review','x'*2001),('start_review','x\x00y')):
            with self.subTest(action=action), self.assertRaises(c.ContractError):
                transition_review(uuid4(),operation_id=uuid4(),action=action,expected_status='UNREVIEWED',reason=reason)
