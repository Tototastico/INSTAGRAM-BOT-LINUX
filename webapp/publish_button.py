"""Find the publish control adjacent to the active comment editor."""
import html

from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By

from .comment_field import comment_candidates


PUBLISH_CONTROL_SELECTOR = 'button, [role="button"], input[type="submit"]'
_LABELS = {'post', 'publicar'}


def _label(element):
    for value in (element.text, element.get_attribute('aria-label'), element.get_attribute('value')):
        label = ' '.join((value or '').split()).casefold()
        if label in _LABELS:
            return label
    return ''


def _editor_value(element):
    tag = (element.tag_name or '').lower()
    if tag in ('textarea', 'input'):
        return element.get_property('value') or ''
    return element.get_property('textContent') or ''


def _structural_markup(editor, button, scope):
    """Record only tag/role/state and a known action label; never outerHTML or values."""
    editor_tag = html.escape((editor.tag_name or 'editor').lower())
    button_tag = html.escape((button.tag_name or 'control').lower()) if button else 'control'
    role = (button.get_attribute('role') or '') if button else ''
    role = role if role in ('button', '') else '[omitido]'
    label = _label(button) if button else '[no encontrado]'
    disabled = bool(button and (not button.is_enabled() or
               (button.get_attribute('aria-disabled') or '').lower() == 'true'))
    return (f'<{html.escape(scope)}><{editor_tag} aria-label="[comentario]" />'
            f'<{button_tag} role="{html.escape(role)}" disabled="{str(disabled).lower()}">'
            f'{html.escape(label or "[otro]")}</{button_tag}></{html.escape(scope)}>')


class PublishButtonProbe:
    def __init__(self, comment):
        self.comment = comment
        self.state = {'editor_matches': 0, 'button_matches': 0, 'visible': 0,
                      'enabled': 0, 'stale_references': 0, 'ambiguous': False,
                      'scope': 'none'}
        self.structure = ''

    def __call__(self, driver):
        stale_count = self.state['stale_references']
        self.state.update({'editor_matches': 0, 'button_matches': 0, 'visible': 0,
                           'enabled': 0, 'stale_references': stale_count,
                           'ambiguous': False, 'scope': 'none'})
        self.structure = ''
        try:
            editors = [element for element, state in comment_candidates(driver)
                       if state['visible'] and state['enabled'] and
                       _editor_value(element) == self.comment and
                       driver.execute_script('return document.activeElement === arguments[0]', element)]
            self.state['editor_matches'] = len(editors)
            if len(editors) != 1:
                self.state['ambiguous'] = len(editors) > 1
                return False
            editor = editors[0]
            forms = editor.find_elements(By.XPATH, './ancestor::form[1]')
            scopes = [('form', forms[0])] if forms else []
            if not forms:
                ancestor = editor
                for depth in range(1, 6):
                    parents = ancestor.find_elements(By.XPATH, './parent::*')
                    if not parents:
                        break
                    ancestor = parents[0]
                    scopes.append((f'ancestor_{depth}', ancestor))
            for scope_name, scope in scopes:
                candidates = scope.find_elements(By.CSS_SELECTOR, PUBLISH_CONTROL_SELECTOR)
                matching = [candidate for candidate in candidates if _label(candidate)]
                self.state.update({'scope': scope_name, 'button_matches': len(matching),
                                   'visible': 0, 'enabled': 0, 'ambiguous': len(matching) > 1})
                if not matching:
                    if candidates and not self.structure:
                        self.structure = _structural_markup(editor, candidates[0], scope_name)
                    continue
                self.state['visible'] = sum(1 for item in matching if item.is_displayed())
                self.state['enabled'] = sum(1 for item in matching if item.is_displayed() and
                    item.is_enabled() and (item.get_attribute('aria-disabled') or '').lower() != 'true')
                self.structure = _structural_markup(editor, matching[0], scope_name)
                if len(matching) != 1:
                    return False
                if self.state['enabled'] != 1:
                    return False
                return editor, matching[0]
            return False
        except StaleElementReferenceException:
            self.state['stale_references'] += 1
            return False


def safe_button_state(probe):
    return dict(probe.state)
