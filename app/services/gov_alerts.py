from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..models import Alert
from ..timeutil import iso, utcnow
from . import feeds, http
from .singleflight import cached_call

log = logging.getLogger("watercast.alerts")
SACHET_HOME = "https://sachet.ndma.gov.in/"
SEV_TIER = {"extreme": "critical", "severe": "warning", "moderate": "watch", "minor": "watch"}


def parse_cap(data: bytes) -> dict | None:
    root = feeds.parse_xml(data)
    infos = [c for c in root if feeds.local(c.tag) == "info"]
    if not infos:
        return None
    info = next((i for i in infos if feeds.child_text(i, "language").lower().startswith("en")), infos[0])
    areas: list[str] = []
    for a in info:
        if feeds.local(a.tag) == "area":
            areas += [x.strip() for x in feeds.child_text(a, "areaDesc").split(",") if x.strip()]
    ct = feeds.child_text
    return {"identifier": ct(root, "identifier"), "sent": ct(root, "sent"), "event": ct(info, "event"),
            "severity": ct(info, "severity"), "headline": ct(info, "headline"), "description": ct(info, "description"),
            "instruction": ct(info, "instruction"), "urgency": ct(info, "urgency"), "certainty": ct(info, "certainty"),
            "effective": ct(info, "effective") or ct(info, "onset"), "expires": ct(info, "expires"),
            "web": ct(info, "web"), "sender_name": ct(info, "senderName"), "sender": ct(root, "sender"),
            "areas": areas}


def fetch_gov_alerts() -> dict:
    return cached_call("gov:alerts", _build_gov_alerts, ok_ttl=600)


def _build_gov_alerts() -> dict:
    cfg = current_app.config
    app = current_app._get_current_object()

    items, errors, ok_feeds, seen = [], [], 0, set()
    for feed in cfg["SACHET_FEEDS"]:
        try:
            got = feeds.feed_items(feeds.parse_xml(http.fetch(feed, timeout=25)))
            ok_feeds += 1
            for it in got:
                k = it.get("guid") or it.get("link") or it.get("title")
                if k not in seen:
                    seen.add(k)
                    items.append(it)
        except (http.UpstreamError, feeds.ParseError) as exc:
            msg = exc.describe() if isinstance(exc, http.UpstreamError) else "the feed was not valid XML"
            errors.append(msg)
            log.warning("SACHET feed %s failed: %s", feed, msg)
    if not ok_feeds:
        res = {"ok": False, "items": [], "detail": errors, "fetched_at": iso(utcnow()), "insecure_tls": False,
               "error": f"Could not load the NDMA SACHET feed - {errors[0] if errors else 'no feeds configured'}."}
        return res

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    rows = sorted(((it, feeds.parse_dt(it.get("pubDate") or it.get("published") or it.get("updated") or it.get("date")))
                   for it in items), key=lambda r: r[1] or epoch, reverse=True)[:150]
    cutoff = utcnow() - timedelta(days=cfg["HOT_ALERT_DAYS"])

    def cap_url(it):
        for k in ("link", "guid"):
            if "FetchXMLFile" in (it.get(k) or ""):
                return it[k]
        return None

    wanted = [(i, it) for i, (it, pub) in enumerate(rows) if cap_url(it) and (i < 40 or (pub and pub >= cutoff))]
    if rows and not wanted:
        log.warning("SACHET feed has %d items but none link to a CAP XML file; fields seen: %s. Alerts will show "
                    "without affected areas.", len(rows), sorted(rows[0][0].keys()))
    caps: dict[int, dict | None] = {}
    cap_errs: list[str] = []

    def work(pair):
        i, it = pair
        with app.app_context():
            try:
                caps[i] = parse_cap(http.fetch(cap_url(it), max_age=6 * 3600, timeout=12))
            except (http.UpstreamError, feeds.ParseError) as exc:
                caps[i] = None
                cap_errs.append(exc.describe() if isinstance(exc, http.UpstreamError) else "invalid CAP XML")

    if wanted:
        with ThreadPoolExecutor(max_workers=8) as ex:
            wait([ex.submit(work, p) for p in wanted], timeout=25)
    if wanted and len(cap_errs) >= len(wanted):
        log.warning("SACHET alert details could not be loaded (%s).", cap_errs[0])

    alerts = []
    for i, (it, pub) in enumerate(rows):
        cap = caps.get(i) or {}
        sent = feeds.parse_dt(cap.get("sent")) or pub
        sev = cap.get("severity") or ""
        title = (cap.get("event") or cap.get("headline") or it.get("title") or "Government alert").strip()
        alerts.append({
            "id": cap.get("identifier") or it.get("guid") or it.get("link") or str(i), "title": title[:200],
            "severity": sev.title() if sev else "Unknown", "tier": SEV_TIER.get(sev.lower(), "watch"),
            "areas": cap.get("areas") or [], "description": feeds.plain(cap.get("description") or it.get("description") or ""),
            "sender": cap.get("sender_name") or "NDMA SACHET", "sent": sent.isoformat() if sent else None,
            "issued_by": _issuer(cap), "headline": feeds.plain(cap.get("headline") or "", 400),
            "details": feeds.plain(cap.get("description") or it.get("description") or "", 1500),
            "instruction": feeds.plain(cap.get("instruction") or "", 600),
            "urgency": cap.get("urgency") or "", "certainty": cap.get("certainty") or "",
            "effective": _iso(cap.get("effective")), "expires": _iso(cap.get("expires")),
            "link": _page_link(cap.get("web")) or _page_link(it.get("link")) or SACHET_HOME})
    alerts.sort(key=lambda a: a["sent"] or "", reverse=True)
    res = {"ok": True, "items": alerts, "error": None, "detail": errors, "fetched_at": iso(utcnow()),
           "insecure_tls": http.tls_was_unverified()}
    return res


def _page_link(url) -> str:
    u = feeds.http_url(url)
    low = u.lower()
    if not u or low.endswith(".xml") or "fetchxmlfile" in low or "fetchpolygonxmlfile" in low or "/rss/" in low:
        return ""
    return u


def _iso(value) -> str | None:
    dt = feeds.parse_dt(value) if value else None
    return dt.isoformat() if dt else None


def _issuer(cap: dict) -> str:
    s = (cap.get("sender") or "").strip()
    return s if s and "@" not in s and not s.lower().startswith("http") else ""


def norm_area(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").split(",")[0]).strip().lower()
    return re.sub(r"\s+(district|dist\.?|city|taluka|tehsil)$", "", n)


def compute_hot_areas(gov_items: list[dict]) -> dict:
    cfg = current_app.config
    threshold, days = cfg["HOT_ALERT_THRESHOLD"], cfg["HOT_ALERT_DAYS"]
    cutoff = utcnow() - timedelta(days=days)
    areas: dict[str, dict] = {}

    def bump(name, source, tier, when, event):
        key = norm_area(name)
        if not key:
            return
        a = areas.setdefault(key, {"name": (name or "").split(",")[0].strip().title(), "count": 0, "gov": 0, "app": 0,
                                   "critical": 0, "warning": 0, "watch": 0, "latest": None, "events": []})
        a["count"] += 1
        a[source] += 1
        a[tier if tier in ("critical", "warning", "watch") else "watch"] += 1
        if when and (not a["latest"] or when > a["latest"]):
            a["latest"] = when
        if event and event not in a["events"] and len(a["events"]) < 3:
            a["events"].append(event)

    for g in gov_items:
        when = feeds.parse_dt(g.get("sent"))
        if when and when >= cutoff:
            for ar in dict.fromkeys(g.get("areas") or []):
                bump(ar, "gov", g.get("tier"), when, g.get("title"))
    for al in Alert.query.filter(Alert.created_at >= cutoff).all():
        bump(al.locality_name, "app", {"critical": "critical", "warning": "warning"}.get((al.severity or "").lower(), "watch"),
             al.created_at, al.category)
    out = []
    for a in areas.values():
        row = dict(a)
        row["latest"] = row["latest"].isoformat() if row["latest"] else None
        out.append(row)
    out.sort(key=lambda a: (-a["count"], a["name"]))
    return {"threshold": threshold, "days": days, "areas": [a for a in out if a["count"] >= threshold],
            "near": [a for a in out if a["count"] < threshold][:5]}
