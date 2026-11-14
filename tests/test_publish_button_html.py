"""Local HTML models of the editor and publish control before/after DOM replacement."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import types

import pytest
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from webapp.publish_button import PublishButtonProbe
from webapp.runner import PendingCommentError, SeleniumRunner


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag_name = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.own_text = ''
        self.stale = False
        self.id = self.attrs.get('id', str(id(self)))

    def _live(self):
        if self.stale:
            raise StaleElementReferenceException('replaced')

    @property
    def text(self):
        self._live()
        return self.own_text + ''.join(child.text for child in self.children)

    def get_attribute(self, name):
        self._live()
        return self.attrs.get(name)

    def get_property(self, name):
        self._live()
        if name in ('value', 'textContent'):
            return self.attrs.get('value', self.text)
        return None

    def is_displayed(self):
        self._live()
        return 'display:none' not in (self.attrs.get('style') or '').replace(' ', '')

    def is_enabled(self):
        self._live()
        return 'disabled' not in self.attrs

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def find_elements(self, by, selector):
        self._live()
        if by == By.XPATH and selector == './ancestor::form[1]':
            parent = self.parent
            while parent:
                if parent.tag_name == 'form':
                    return [parent]
                parent = parent.parent
            return []
        if by == By.XPATH and selector == './parent::*':
            return [self.parent] if self.parent else []
        assert by == By.CSS_SELECTOR and 'role="button"' in selector
        return [node for node in self.descendants() if node.tag_name == 'button' or
                node.attrs.get('role') == 'button' or
                (node.tag_name == 'input' and node.attrs.get('type') == 'submit')]


class Page(HTMLParser):
    def __init__(self, filename):
        super().__init__()
        self.root = Node('root', {})
        self.stack = [self.root]
        self.feed((Path(__file__).parent / 'fixtures' / filename).read_text(encoding='utf-8'))
        self.nodes = {node.id: node for node in self.root.descendants()}
        self.active = None

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in ('input', 'br', 'meta'):
            self.stack.append(node)

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1].tag_name == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].own_text += data

    def find_elements(self, by, selector):
        assert by == By.CSS_SELECTOR and 'textarea' in selector
        return [node for node in self.root.descendants() if node.tag_name in ('textarea', 'input') or
                node.attrs.get('contenteditable') == 'true' or node.attrs.get('role') == 'textbox']

    def execute_script(self, script, element):
        assert 'activeElement' in script
        return element is self.active


def test_replaced_editor_relocates_post_in_same_form_without_private_html():
    before = Page('publish_before.html')
    before.active = before.nodes['editor-old']
    probe = PublishButtonProbe('private comment text')
    assert not probe(before)
    assert probe.state['editor_matches'] == 0

    before.nodes['editor-old'].stale = True
    assert not probe(before)
    assert probe.state['stale_references'] == 1
    after = Page('publish_after.html')
    after.active = after.nodes['editor-new']
    editor, button = probe(after)
    assert editor is after.nodes['editor-new']
    assert button is after.nodes['post-new']
    assert probe.state['scope'] == 'form'
    assert probe.state['button_matches'] == probe.state['enabled'] == 1
    assert probe.state['stale_references'] == 1
    assert 'post' in probe.structure
    assert 'private comment text' not in probe.structure
    assert 'token=secret' not in probe.structure


def test_disabled_button_and_unrelated_post_are_not_selected():
    page = Page('publish_before.html')
    page.active = page.nodes['editor-old']
    probe = PublishButtonProbe('')
    assert not probe(page)
    assert probe.state['button_matches'] == 1
    assert probe.state['visible'] == 1 and probe.state['enabled'] == 0
    assert probe.state['scope'] == 'form'


def test_spanish_submit_button_is_scoped_to_active_input():
    page = Page('publish_spanish.html')
    page.active = page.nodes['editor-es']
    probe = PublishButtonProbe('comentario de prueba')
    editor, button = probe(page)
    assert editor.id == 'editor-es'
    assert button.id == 'publish-es'
    assert probe.state['enabled'] == 1


def test_contenteditable_without_form_uses_nearest_shared_ancestor():
    page = Page('publish_no_form.html')
    page.active = page.nodes['editor-rich']
    probe = PublishButtonProbe('sample text')
    editor, button = probe(page)
    assert editor.id == 'editor-rich'
    assert button.id == 'publish-rich'
    assert probe.state['scope'] == 'ancestor_2'


def test_uncertain_publish_click_is_never_retried(monkeypatch):
    calls = []
    field = types.SimpleNamespace(get_property=lambda name: '')
    driver = types.SimpleNamespace(current_url='https://www.instagram.com/p/ABC/', quit=lambda: None)

    def uncertain_click(comment, used_driver, used_field):
        calls.append('click')
        error = WebDriverException('No se conoce el resultado del comando')
        error.bot_operation = 'publish_button.click'
        raise error

    monkeypatch.setitem(sys.modules, 'selenium_runner', types.SimpleNamespace(
        acceder_caja=lambda url, profile: (True, driver, field),
        comentar_en_post=uncertain_click))
    runner = SeleniumRunner()
    runner.open('https://www.instagram.com/p/ABC/', 'cuenta1')
    with pytest.raises(PendingCommentError, match='incierto'):
        runner.post('comentario de prueba')
    assert calls == ['click']
    runner.close()
