"""Identify a comment editor by semantics and editability, not CSS classes."""
import re

from selenium.webdriver.common.by import By


COMMENT_CANDIDATE_SELECTOR = 'textarea, input, [contenteditable="true"], [role="textbox"]'
_COMMENT_CUE = re.compile(r'comment|coment', re.IGNORECASE)
_CUE_ATTRIBUTES = ('aria-label', 'placeholder', 'aria-placeholder', 'data-placeholder', 'name')


def comment_field_state(element):
    """Return safe facts about a candidate without reading its value or page text."""
    def attribute(name):
        try:
            return element.get_attribute(name)
        except Exception as exc:
            exc.bot_operation = f'comment_field.get_attribute:{name}'
            raise

    try:
        tag = (element.tag_name or '').lower()
    except Exception as exc:
        exc.bot_operation = 'comment_field.tag_name'
        raise
    input_type = (attribute('type') or 'text').lower()
    editable = (tag == 'textarea' or
                (tag == 'input' and input_type == 'text') or
                attribute('contenteditable') == 'true')
    cue = any(_COMMENT_CUE.search(attribute(name) or '') for name in _CUE_ATTRIBUTES)
    if not editable or not cue:
        return {'tag': tag, 'editable': editable, 'comment_cue': cue,
                'visible': False, 'enabled': False}
    try:
        visible = bool(element.is_displayed())
    except Exception as exc:
        exc.bot_operation = 'comment_field.is_displayed'
        raise
    try:
        enabled = bool(element.is_enabled())
    except Exception as exc:
        exc.bot_operation = 'comment_field.is_enabled'
        raise
    readonly = attribute('readonly') is not None
    aria_disabled = (attribute('aria-disabled') or '').lower() == 'true'
    return {'tag': tag, 'editable': editable, 'comment_cue': cue,
            'visible': visible, 'enabled': enabled and not readonly and not aria_disabled}


def comment_candidates(driver):
    """Return recognized editors and their safe state; ignore unrelated search fields."""
    found = []
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, COMMENT_CANDIDATE_SELECTOR)
    except Exception as exc:
        exc.bot_operation = 'comment_field.find_elements'
        raise
    for element in elements:
        state = comment_field_state(element)
        if state['editable'] and state['comment_cue']:
            found.append((element, state))
    return found


def ready_comment_field(driver):
    for element, state in comment_candidates(driver):
        if state['visible'] and state['enabled']:
            return element
    return False


def confirm_comment_field(element):
    state = comment_field_state(element)
    return state['editable'] and state['comment_cue'] and state['visible'] and state['enabled']
