from comentarios import generar_comentario


class PendingCommentError(RuntimeError):
    pass


def compose_comment(tags, tag_count, extra_text):
    if not tags:
        raise ValueError('La asignacion necesita al menos una etiqueta')
    generated = generar_comentario(tags, tag_count)
    text = f'{generated} {extra_text.strip()}'.strip()
    return ''.join(char for char in text if ord(char) <= 0xFFFF)


class SeleniumRunner:
    def __init__(self):
        self.driver = None
        self.textarea = None

    def open(self, url, profile_arg):
        from selenium_runner import acceder_caja

        success, self.driver, self.textarea = acceder_caja(url, profile_arg)
        if not success:
            self._check_session()
            raise RuntimeError('No se pudo abrir la caja de comentarios; revisa la sesion o la interfaz')
        self._check_session()

    def post(self, comment):
        from selenium_runner import comentar_en_post

        self._check_session()
        pending = self.textarea.get_dom_property('value')
        if pending is None:
            pending = self.textarea.get_attribute('value')
        if pending and pending.strip():
            raise PendingCommentError('La caja de comentarios conserva texto; posible bloqueo o comentario pendiente')
        comentar_en_post(comment, self.driver, self.textarea)

    def _check_session(self):
        if self.driver is None:
            return
        url = (getattr(self.driver, 'current_url', '') or '').lower()
        if '/accounts/login' in url:
            raise RuntimeError('Sesion vencida: inicia sesion manualmente en el perfil')
        if '/challenge' in url or '/checkpoint' in url:
            raise RuntimeError('Instagram solicita una verificacion manual')

    def close(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
