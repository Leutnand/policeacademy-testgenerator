"""Template-Filter für sicher verlinkten Infotext."""

import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
BARE_URL = re.compile(r"(https?://[^\s\x00<]+[^\s\x00<.,;:!?)])")


@register.filter
def linkify(value):
    """Wandelt [Text](https://…) und nackte URLs in sichere Links um; alles andere wird escaped."""
    links = []

    def stash(text, url):
        links.append(
            format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                url,
                text,
            )
        )
        return f"\x00{len(links) - 1}\x00"

    text = MARKDOWN_LINK.sub(lambda m: stash(m.group(1), m.group(2)), value or "")
    text = BARE_URL.sub(lambda m: stash(m.group(1), m.group(1)), text)
    text = escape(text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: str(links[int(m.group(1))]), text)
    return mark_safe(text)
