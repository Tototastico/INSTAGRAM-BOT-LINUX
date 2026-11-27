"""Normalize an Instagram post URL without changing its shortcode or query."""
import re
from urllib.parse import urlsplit, urlunsplit


def normalize_post_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('instagram.com', 'www.instagram.com')
                or parsed.username or parsed.password or parsed.port):
            return url
    except (TypeError, ValueError):
        return url
    match = re.fullmatch(r'/reel/([A-Za-z0-9_-]+)/?', parsed.path)
    if not match:
        return url
    return urlunsplit(parsed._replace(path=f'/p/{match.group(1)}/'))
