from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlencode

from flask import current_app

from ..timeutil import iso, utcnow
from . import feeds, http
from .singleflight import cached_call

log = logging.getLogger("watercast.news")

RAIN_QUERIES = [
    'monsoon delayed OR delay OR "yet to" India',
    'rainfall deficit OR "dry spell" India',
    'unseasonal rain India',
    'sudden heavy rain OR cloudburst OR "flash flood" India',
    'heavy rainfall IMD alert India',
    'excess rainfall OR "too much rain" OR waterlogging India',
]
INFRA_QUERIES = [
    'dam OR reservoir "water level" India',
    'drinking water pipeline OR "water supply project" India',
    'water tanker shortage India',
    'borewell OR groundwater depletion India',
    '"Jal Jeevan Mission" OR "water supply scheme" India',
    'sewage treatment plant OR "water treatment plant" India',
]

RAIN_RE = re.compile(r"\b(rain|rains|rainfall|rainy|monsoon|shower|showers|downpour|cloudburst|deluge|hail|hailstorm|thunderstorm|drizzle|flood|floods|flooding|waterlogging)\b", re.I)
RAIN_TAGS = {
    "delayed": re.compile(r"\bdelay(?:ed|s)?\b|late onset|deferred|\bstall(?:ed|s)?\b|yet to (?:arrive|set in|reach|advance|revive|withdraw|begin)|\bnot yet\b|fail(?:s|ed)? to|rain(?:fall)? (?:deficit|shortfall)|\bdeficient\b|\bdry spell\b|weak monsoon|break in monsoon|sluggish|below[- ]normal|erratic|\blate\b", re.I),
    "unseasonal": re.compile(r"unseasonal|untimely|out[- ]of[- ]season|off[- ]season|unusual(?:ly)? (?:rain|wet|heavy)|unexpected (?:rain|shower|downpour|rainfall)|rains? in (?:winter|summer|december|january|february|march|april|may)|western disturbance|post[- ]monsoon (?:rain|shower)|pre[- ]monsoon (?:rain|shower)", re.I),
    "sudden": re.compile(r"\bsudden(?:ly)?\b|flash flood|cloudburst|cloud burst|torrential|out of the blue|\babrupt|\bsqualls?\b|\blash(?:es|ed)?\b|drench", re.I),
    "excess": re.compile(r"heavy rain|heavy showers|very heavy|extremely heavy|exceptionally heavy|excess(?:ive)? rain|too much rain|incessant|record(?:-breaking)? rain|deluge|waterlogg|inundat|flood|red alert|orange alert|overflow|swollen|above[- ]normal|surplus|downpour|torrential|continuous rain", re.I),
}
DELAY_NOISE = re.compile(r"flights?|airport|runway|trains?|railway|metro|\bmatch(?:es)?\b|cricket|\bipl\b|t20|\bodi\b|test series|football|stadium|traffic|exams?|school", re.I)

INFRA_WATER_RE = re.compile(r"\b(water|dam|dams|reservoir|reservoirs|pipeline|pipelines|borewell|borewells|groundwater|tanker|tankers|sewage|jal jeevan|irrigation|canal|aquifer|desalination)\b", re.I)
INFRA_TAGS = {
    "dams": re.compile(r"\bdams?\b|reservoir|\bstorage\b|catchment|water level|barrage|\bcanals?\b", re.I),
    "pipelines": re.compile(r"pipeline|water supply|supply scheme|jal jeevan|tap water|water distribution|piped water|water (?:project|scheme)|\bamrut\b", re.I),
    "tankers": re.compile(r"\btankers?\b", re.I),
    "groundwater": re.compile(r"borewell|bore well|groundwater|ground water|water table|aquifer|recharge", re.I),
    "treatment": re.compile(r"treatment plant|sewage|\bstp\b|wastewater|desalination|water purification|recycl", re.I),
}


def classify_rain(title: str, desc: str = "") -> list[str]:
    text = f"{title} {desc}".strip()
    if not RAIN_RE.search(text):
        return []
    tags = []
    for tag, rx in RAIN_TAGS.items():
        if rx.search(text) and not (tag == "delayed" and DELAY_NOISE.search(text)):
            tags.append(tag)
    return tags


def classify_infra(title: str, desc: str = "") -> list[str]:
    text = f"{title} {desc}".strip()
    if not INFRA_WATER_RE.search(text):
        return []
    return [tag for tag, rx in INFRA_TAGS.items() if rx.search(text)]


def _urls(queries: list[str]) -> list[str]:
    cfg = current_app.config
    if cfg["NEWS_SOURCE"] == "rss":
        return list(cfg["NEWS_RSS_FEEDS"])
    return ["https://news.google.com/rss/search?" + urlencode({"q": q + " when:7d", "hl": "en-IN", "gl": "IN",
                                                              "ceid": "IN:en"}) for q in queries]


def collect(cache_key: str, queries: list[str], classify, tag_names: list[str]) -> dict:
    return cached_call(cache_key, lambda: _build(queries, classify, tag_names), ok_ttl=900)


def _build(queries: list[str], classify, tag_names: list[str]) -> dict:
    cfg = current_app.config
    if not cfg["NEWS_ENABLED"]:
        return {"ok": False, "items": [], "counts": {}, "detail": [], "fetched_at": iso(utcnow()),
                "error": "News feeds are switched off on this server."}
    urls = _urls(queries)
    if not urls:
        return {"ok": False, "items": [], "counts": {}, "detail": [], "fetched_at": iso(utcnow()),
                "error": "No news feeds are configured (set NEWS_RSS_FEEDS)."}
    app = current_app._get_current_object()
    results: list[dict] = []
    errors: list[str] = []

    def work(u):
        with app.app_context():
            try:
                results.extend(feeds.feed_items(feeds.parse_xml(http.fetch(u, timeout=15))))
            except (http.UpstreamError, feeds.ParseError) as exc:
                errors.append(exc.describe() if isinstance(exc, http.UpstreamError) else "invalid feed")
                log.warning("news feed failed: %s", errors[-1])

    with ThreadPoolExecutor(max_workers=6) as ex:
        wait([ex.submit(work, u) for u in urls], timeout=30)
    if len(errors) >= len(urls):
        res = {"ok": False, "items": [], "counts": {}, "detail": errors, "fetched_at": iso(utcnow()),
               "error": f"Could not load the news feed - {errors[0]}."}
        return res

    seen, items = set(), []
    for r in results:
        raw = (r.get("title") or "").strip()
        src = r.get("source") or ""
        title = raw[: -len(src) - 3].strip() if src and raw.endswith(" - " + src) else raw
        if " - " in title and not src:
            title, src = title.rsplit(" - ", 1)
        key = re.sub(r"[^a-z0-9]", "", title.lower())[:60]
        link = feeds.http_url(r.get("link"))
        if not title or not link or key in seen:
            continue
        tags = classify(title, feeds.plain(r.get("description") or "", 200) if not src else "")
        if not tags:
            continue
        seen.add(key)
        when = feeds.parse_dt(r.get("pubDate") or r.get("published") or r.get("updated"))
        items.append({"title": title[:240], "source": src[:60], "link": link, "tags": tags,
                      "published": when.isoformat() if when else None})
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    items = items[:60]
    res = {"ok": True, "items": items, "counts": {t: sum(1 for i in items if t in i["tags"]) for t in tag_names},
           "error": None, "detail": errors, "fetched_at": iso(utcnow())}
    return res


def rain_news() -> dict:
    return collect("news:rain", RAIN_QUERIES, classify_rain, list(RAIN_TAGS))


def infra_news() -> dict:
    return collect("news:infra", INFRA_QUERIES, classify_infra, list(INFRA_TAGS))


POPULAR_SOURCES = (
    "times of india", "the times of india", "hindustan times", "the hindu", "indian express", "the indian express",
    "ndtv", "india today", "news18", "cnn-news18", "mint", "livemint", "deccan herald", "deccan chronicle",
    "the economic times", "economic times", "business standard", "the print", "theprint", "scroll", "the quint",
    "firstpost", "wion", "zee news", "abp live", "republic world", "the statesman", "the tribune", "tribune india",
    "the new indian express", "new indian express", "telangana today", "the federal", "onmanorama", "mathrubhumi",
    "malayala manorama", "lokmat", "loksatta", "maharashtra times", "free press journal", "mid-day", "dna india",
    "the telegraph", "telegraph india", "bbc", "reuters", "associated press", "ap news", "al jazeera",
    "down to earth", "moneycontrol", "outlook india", "the week", "news9live", "dainik bhaskar", "amar ujala",
    "jagran", "dainik jagran", "navbharat times", "times now", "india tv", "aaj tak", "the pioneer", "sakal",
)
AREA_NOISE = re.compile(r"\b(districts?|dist\.?|city|taluka|tehsil|block|region|state|and|of|the)\b", re.I)
EVENT_STOP = {"of", "the", "and", "for", "in", "to", "a", "warning", "alert", "advisory", "bulletin", "update",
              "forecast", "nowcast", "likely", "expected", "possibility"}


def is_popular(source: str) -> bool:
    s = (source or "").strip().lower()
    return bool(s) and any(s == p or s.startswith(p + " ") or p in s for p in POPULAR_SOURCES)


def _area_terms(areas: list[str]) -> list[str]:
    out = []
    for a in areas:
        for part in re.split(r"[,/;]| and ", a or ""):
            t = re.sub(r"\s+", " ", AREA_NOISE.sub(" ", part)).strip()
            if len(t) >= 3 and t.lower() not in [x.lower() for x in out]:
                out.append(t.title())
    return out[:4]


def _event_terms(event: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]+", (event or "").lower()) if w not in EVENT_STOP and len(w) > 2]
    return list(dict.fromkeys(words))[:3]


def alert_coverage(event: str, areas: list[str], sent: str | None = None) -> dict:
    cfg = current_app.config
    if not cfg["NEWS_ENABLED"]:
        return {"ok": False, "items": [], "error": "News feeds are switched off on this server."}
    terms, ev = _area_terms(areas), _event_terms(event)
    if not terms:
        return {"ok": True, "items": [], "query": ""}
    area_q = " OR ".join(f'"{t}"' for t in terms)
    ev_q = " OR ".join(ev + ["rain", "IMD", "alert"]) if ev else "rain OR flood OR IMD OR alert"
    query = f"({area_q}) ({ev_q})"
    key = "news:cov:" + re.sub(r"[^a-z0-9]+", "-", query.lower())[:180]

    def build():
        url = "https://news.google.com/rss/search?" + urlencode(
            {"q": query + " when:3d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        try:
            raw = feeds.feed_items(feeds.parse_xml(http.fetch(url, timeout=15)))
        except (http.UpstreamError, feeds.ParseError) as exc:
            msg = exc.describe() if isinstance(exc, http.UpstreamError) else "invalid feed"
            return {"ok": False, "items": [], "error": f"Could not reach the news search - {msg}."}
        low_terms = [t.lower() for t in terms]
        seen, items = set(), []
        for r in raw:
            src = (r.get("source") or "").strip()
            title = (r.get("title") or "").strip()
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3].strip()
            link = feeds.http_url(r.get("link"))
            k = re.sub(r"[^a-z0-9]", "", title.lower())[:60]
            if not title or not link or k in seen or not is_popular(src):
                continue
            if not any(t in title.lower() for t in low_terms):
                continue
            seen.add(k)
            when = feeds.parse_dt(r.get("pubDate") or r.get("published"))
            items.append({"title": title[:240], "source": src[:60], "link": link,
                          "published": when.isoformat() if when else None})
        items.sort(key=lambda x: x["published"] or "", reverse=True)
        return {"ok": True, "items": items[:5], "query": query}

    return cached_call(key, build, ok_ttl=1800, fail_ttl=60, wait=20)
