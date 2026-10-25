from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SafeET


def parse_xml(data: bytes):
    return SafeET.fromstring(data)


def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child_text(el, name: str) -> str:
    for c in el:
        if local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def feed_items(root) -> list[dict]:
    out = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        d: dict = {}
        for ch in el:
            k = local(ch.tag)
            if k == "link":
                d.setdefault("link", (ch.text or "").strip() or ch.get("href") or "")
            elif k == "source":
                d.setdefault("source", (ch.text or "").strip())
            else:
                d.setdefault(k, (ch.text or "").strip())
        out.append(d)
    return out


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def http_url(value) -> str:
    return value if isinstance(value, str) and value.lower().startswith(("http://", "https://")) else ""


def plain(text: str, limit: int = 300) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "..."
