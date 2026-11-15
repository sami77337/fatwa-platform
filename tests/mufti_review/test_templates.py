"""Parse rendered options rather than searching HTML strings."""
from html.parser import HTMLParser
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class DecisionTemplateTests(SimpleTestCase):
    def test_all_three_decisions_are_real_select_options(self):
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_select = False
                self.options = []
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == 'select' and values.get('id') == 'decision-action':
                    self.in_select = True
                if tag == 'option' and self.in_select:
                    self.options.append(values.get('value'))
            def handle_endtag(self, tag):
                if tag == 'select':
                    self.in_select = False
        html = render_to_string('mufti_review/review.html', {'package': {'question': {},
            'answer': {}, 'evidence': {}, 'segments': [], 'request_sha256': 'a' * 64},
            'state': 'PENDING_REVIEW', 'command_id': 'b' * 32, 'confirmation': 'c' * 64})
        parsed = Parser()
        parsed.feed(html)
        self.assertEqual(parsed.options, ['', 'RETURN_FOR_CHANGES', 'DECLINED', 'READY_FOR_SIGNATURE'])
