"""Local HTML structures; these tests never navigate to Instagram."""
from html.parser import HTMLParser
from pathlib import Path

from webapp.comment_field import comment_candidates, confirm_comment_field, ready_comment_field


class Element:
    def __init__(self, tag, attrs):
        self.tag_name = tag
        self.attrs = dict(attrs)

    def get_attribute(self, name):
        if name in ('readonly', 'disabled') and name in self.attrs:
            return 'true'
        return self.attrs.get(name)

    def is_displayed(self):
        return 'display:none' not in (self.get_attribute('style') or '').replace(' ', '')

    def is_enabled(self):
        return 'disabled' not in self.attrs


class ParsedHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        if tag in ('textarea', 'input', 'div'):
            self.elements.append(Element(tag, attrs))

    def find_elements(self, by, selector):
        assert 'textarea' in selector and 'contenteditable' in selector
        return self.elements


def test_local_html_identifies_only_editable_comment_fields():
    page = ParsedHTML()
    page.feed((Path(__file__).parent / 'fixtures' / 'comment_fields.html').read_text(encoding='utf-8'))
    matched = {element.get_attribute('id'): state for element, state in comment_candidates(page)}
    assert set(matched) == {'textarea-en', 'textarea-es', 'input-comment', 'rich-editor',
                            'hidden-editor', 'disabled-editor', 'readonly-textarea'}
    for name in ('textarea-en', 'textarea-es', 'input-comment', 'rich-editor'):
        assert matched[name]['visible'] and matched[name]['enabled']
    for name in ('hidden-editor', 'disabled-editor', 'readonly-textarea'):
        assert not (matched[name]['visible'] and matched[name]['enabled'])
    assert ready_comment_field(page).get_attribute('id') == 'textarea-en'


def test_local_html_rejects_search_and_noneditable_or_hidden_fields():
    page = ParsedHTML()
    page.feed((Path(__file__).parent / 'fixtures' / 'comment_fields.html').read_text(encoding='utf-8'))
    elements = {element.get_attribute('id'): element for element in page.elements}
    for name in ('search', 'readonly-editor', 'hidden-editor', 'disabled-editor', 'readonly-textarea'):
        assert not confirm_comment_field(elements[name])
