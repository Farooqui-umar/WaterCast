from __future__ import annotations

import math
import time

from flask import current_app

from ..extensions import cache
from . import http


def _uniq(parts):
    seen, out = set(), []
    for p in parts:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def _throttle() -> None:
    interval = current_app.config["GEOCODER_MIN_INTERVAL"]
    if interval <= 0:
        return
    ttl = max(1, math.ceil(interval))
    deadline = time.time() + 8
    while not cache.add("geocoder:lock", 1, timeout=ttl):
        if time.time() > deadline:
            return
        time.sleep(0.15)


def _geocoder_params(params: dict) -> dict:
    cfg = current_app.config
    params = dict(params)
    if cfg["GEOCODER_API_KEY"]:
        params[cfg["GEOCODER_KEY_PARAM"]] = cfg["GEOCODER_API_KEY"]
    elif cfg["CONTACT_EMAIL"] and "nominatim.openstreetmap.org" in cfg["GEOCODER_URL"]:
        params["email"] = cfg["CONTACT_EMAIL"]
    return params


def open_meteo_search(q: str, count: int = 8) -> list[dict]:
    cfg = current_app.config
    params = {"name": q.split(",")[0].strip(), "count": count, "language": "en", "format": "json"}
    if cfg["OPEN_METEO_API_KEY"]:
        params["apikey"] = cfg["OPEN_METEO_API_KEY"]
    data = http.fetch_json(cfg["OPEN_METEO_GEOCODING_URL"], params=params)
    out = []
    for r in data.get("results") or []:
        name = r.get("name") or ""
        ctx = _uniq([r.get("admin3"), r.get("admin2"), r.get("admin1"), r.get("country")])
        out.append({"name": name, "context": ", ".join(c for c in ctx if c.lower() != name.lower()),
                    "state": r.get("admin1") or "", "country": r.get("country") or "",
                    "lat": r["latitude"], "lon": r["longitude"], "kind": r.get("feature_code") or "",
                    "source": "open-meteo"})
    return out


def nominatim_search(q: str, count: int = 8) -> list[dict]:
    cfg = current_app.config
    _throttle()
    rows = http.fetch_json(cfg["GEOCODER_URL"], params=_geocoder_params(
        {"q": q, "format": "jsonv2", "addressdetails": 1, "limit": count, "accept-language": "en", "dedupe": 1}))
    out = []
    for r in rows if isinstance(rows, list) else []:
        addr = r.get("address") or {}
        name = r.get("name") or addr.get(r.get("addresstype") or "") or (r.get("display_name") or "").split(",")[0]
        ctx = _uniq([
            addr.get("suburb") or addr.get("neighbourhood") or addr.get("city_district") or addr.get("quarter"),
            addr.get("hamlet") or addr.get("village") or addr.get("town") or addr.get("city") or addr.get("municipality"),
            addr.get("state_district") or addr.get("county"), addr.get("state"), addr.get("country"),
        ])
        out.append({"name": name, "context": ", ".join(c for c in ctx if c.lower() != (name or "").lower()),
                    "state": addr.get("state") or "", "country": addr.get("country") or "",
                    "lat": float(r["lat"]), "lon": float(r["lon"]),
                    "kind": f"{r.get('category') or ''}:{r.get('type') or ''}", "source": "openstreetmap",
                    "_place": r.get("category") in ("place", "boundary")})
    out.sort(key=lambda x: 0 if x["_place"] else 1)
    if any(x["_place"] for x in out):
        out = [x for x in out if x["_place"] or x["kind"].split(":")[0] not in ("highway", "railway")]
    for x in out:
        x.pop("_place", None)
    return out


def _merge(*lists):
    seen, out = set(), []
    for lst in lists:
        for p in lst:
            key = ((p.get("name") or "").lower(), round(p["lat"], 2), round(p["lon"], 2))
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out


def _rank_by_hint(places: list[dict], q: str) -> list[dict]:
    hint = " ".join(q.split(",")[1:]).strip().lower()
    if not hint:
        return places
    toks = [t for t in hint.replace(",", " ").split() if len(t) > 1]

    def score(p):
        hay = f"{p.get('context') or ''} {p.get('state') or ''} {p.get('country') or ''}".lower()
        return -sum(1 for t in toks if t in hay)
    return sorted(places, key=score)


def lookup(q: str, mode: str = "suggest") -> list[dict]:
    key = f"geo:{mode}:{q.lower()}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    providers = [open_meteo_search] if mode == "suggest" else [nominatim_search, open_meteo_search]
    found, errors = [], []
    for fn in providers:
        try:
            found.append(fn(q))
        except http.UpstreamError as exc:
            errors.append(exc)
            current_app.logger.warning("geocoder %s failed: %s", fn.__name__, exc.describe())
    if errors and len(errors) == len(providers):
        raise errors[0]
    results = _rank_by_hint(_merge(*found), q)[:8]
    cache.set(key, results, timeout=6 * 3600 if not errors else 30)
    return results


def reverse(lat: float, lon: float) -> dict:
    cfg = current_app.config
    key = f"rev:{round(lat, 3)}:{round(lon, 3)}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    place = {"label": None, "place": None, "state": "", "country": "", "exact": False}
    try:
        _throttle()
        data = http.fetch_json(cfg["GEOCODER_REVERSE_URL"], params=_geocoder_params(
            {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18, "addressdetails": 1, "accept-language": "en"}))
        addr = data.get("address") or {}
        fine = (addr.get("neighbourhood") or addr.get("suburb") or addr.get("quarter") or addr.get("hamlet")
                or addr.get("village") or addr.get("city_district"))
        town = (addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
                or addr.get("county"))
        parts = _uniq([fine, town, addr.get("state")])
        if parts:
            place = {"label": ", ".join(parts), "place": fine or town, "state": addr.get("state") or "",
                     "country": addr.get("country") or "", "exact": True}
    except http.UpstreamError as exc:
        current_app.logger.warning("reverse geocoding failed: %s", exc.describe())
    cache.set(key, place, timeout=24 * 3600 if place["exact"] else 30)
    return place
