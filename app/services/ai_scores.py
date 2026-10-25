from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import timedelta

from flask import current_app

from ..extensions import cache, db
from ..models import Alert, SOSRequest, TrustScore, Vote
from ..timeutil import iso, utcnow
from . import feeds, gemini, gov_alerts, http, weather
from .singleflight import cached_call

log = logging.getLogger("watercast.ai")

LABELS = ["New Reporter", "Active Reporter", "Verified Reporter", "Low Reliability"]
LEVELS = ["Critical", "Warning", "Watch"]
TRENDS = ["rising", "steady", "falling"]

TRUST_SYSTEM = (
    "You are the reliability auditor for WaterCast, a citizen water-shortage reporting service in India. "
    "You receive every recent help request filed from one anonymous device together with independent evidence "
    "gathered by the server. Judge how trustworthy this reporter is. Raise the score for reports that are specific, "
    "plausible, carry a photo, are corroborated by other devices, citizen confirmations, official alerts, or were "
    "acted on by officials (In Progress or Resolved). Lower it for vague, contradictory, duplicated, spammy or "
    "exaggerated reports (for example many Critical reports with no corroboration). A single plain report with no "
    "evidence either way should land around 50-60. confirmed_accurate is how many of the listed reports you consider "
    "supported by the evidence. summary is one short plain sentence for the reporter, no more than 120 characters. "
    "Use only the data given."
)

TRUST_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "score": {"type": "INTEGER"},
        "label": {"type": "STRING", "enum": LABELS},
        "confirmed_accurate": {"type": "INTEGER"},
        "summary": {"type": "STRING"},
    },
    "required": ["score", "label", "confirmed_accurate", "summary"],
}

RISK_SYSTEM = (
    "You are the water-risk analyst for WaterCast, a service that warns water-scarce regions in India. "
    "You receive this week's live signals: citizen help requests, citizen confirmations, alerts raised in the app, "
    "official NDMA SACHET government alerts, and measured rainfall for some places. Pick up to 5 places that carry "
    "the highest water-related risk this week (shortage, contamination, drought, or flooding that damages supply) "
    "and give each a risk score from 0 to 100. Weigh Critical requests, many distinct reporters, official alerts, "
    "long dry spells and little forecast rain most heavily. trend compares this week with last week's counts. "
    "reason is one short plain sentence of at most 90 characters naming the main driver. Only use place names that "
    "appear in the data, spelled exactly as given. Skip places whose signals are not about water or weather risk."
)

RISK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "place": {"type": "STRING"},
                    "score": {"type": "INTEGER"},
                    "level": {"type": "STRING", "enum": LEVELS},
                    "trend": {"type": "STRING", "enum": TRENDS},
                    "reason": {"type": "STRING"},
                },
                "required": ["place", "score", "level", "trend", "reason"],
            },
        }
    },
    "required": ["items"],
}


def _fp(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _clamp(v, lo, hi) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


def _gov_items() -> list[dict]:
    try:
        res = gov_alerts.fetch_gov_alerts()
        return res.get("items", []) if res.get("ok") else []
    except Exception:
        log.warning("Government alerts unavailable for AI scoring", exc_info=True)
        return []


def _gov_index(items: list[dict]) -> list[tuple]:
    out = []
    for g in items:
        when = feeds.parse_dt(g.get("sent"))
        if when:
            out.append((when, [gov_alerts.norm_area(a) for a in g.get("areas") or []]))
    return out


def _gov_hits(index: list[tuple], locality: str, start, end) -> int:
    key = gov_alerts.norm_area(locality)
    if not key:
        return 0
    return sum(1 for when, areas in index if start <= when <= end and any(key == a or key in a for a in areas))


def _in_window(rows: list[tuple], start, end) -> list[tuple]:
    return [r for r in rows if start <= r[-1] <= end]


def trust_view_key(dev: str) -> str:
    return f"ai:trustview:{dev}"


def invalidate_trust(dev: str | None) -> None:
    if dev:
        cache.delete(trust_view_key(dev))


def trust_for_device(dev: str) -> dict:
    hit = cache.get(trust_view_key(dev))
    if hit is not None:
        return hit
    res = _trust_for_device(dev)
    cache.set(trust_view_key(dev), res, timeout=60 if res.get("ok") else 20)
    return res


def _trust_for_device(dev: str) -> dict:
    total = SOSRequest.query.filter(SOSRequest.device_id == dev).count()
    base = {"device_id": dev, "reports_filed": total, "source": "gemini"}
    if not total:
        return {**base, "ok": True, "score": None, "confirmed_accurate": 0, "label": "No reports yet", "summary": ""}
    if not gemini.configured():
        return {**base, "ok": False, "score": None, "confirmed_accurate": None, "error": "Gemini API key is not set"}

    rows = (SOSRequest.query.filter(SOSRequest.device_id == dev)
            .order_by(SOSRequest.created_at.desc()).limit(20).all())
    span = timedelta(hours=72)
    lo, hi = min(r.created_at for r in rows) - span, max(r.created_at for r in rows) + span
    locs = sorted({r.locality_name.lower() for r in rows})
    lower_sos, lower_vote, lower_alert = (db.func.lower(SOSRequest.locality_name), db.func.lower(Vote.locality_name),
                                          db.func.lower(Alert.locality_name))
    by_loc: dict[str, dict[str, list]] = defaultdict(lambda: {"sos": [], "votes": [], "alerts": []})
    for loc, device, when in (db.session.query(lower_sos, SOSRequest.device_id, SOSRequest.created_at)
                              .filter(lower_sos.in_(locs), SOSRequest.device_id != dev,
                                      SOSRequest.created_at.between(lo, hi))):
        by_loc[loc]["sos"].append((device, when))
    for loc, when in (db.session.query(lower_vote, Vote.created_at)
                      .filter(lower_vote.in_(locs), Vote.device_id != dev, Vote.created_at.between(lo, hi))):
        by_loc[loc]["votes"].append((when,))
    for loc, when in (db.session.query(lower_alert, Alert.created_at)
                      .filter(lower_alert.in_(locs), Alert.created_at.between(lo, hi),
                              db.or_(Alert.category.is_(None), Alert.category != "Citizen reports"))):
        by_loc[loc]["alerts"].append((when,))
    gov = _gov_index(_gov_items())

    reports = []
    for r in rows:
        ev = by_loc[r.locality_name.lower()]
        start, end = r.created_at - span, r.created_at + span
        reports.append({
            "id": r.id, "date": r.created_at.date().isoformat(), "locality": r.locality_name,
            "issue": r.issue_type, "urgency": r.urgency, "has_photo": r.has_photo,
            "official_status": r.status, "description": (r.description or "")[:300],
            "other_devices_reporting_same_place_72h": len({d for d, _ in _in_window(ev["sos"], start, end)}),
            "citizen_confirmations_same_place_72h": len(_in_window(ev["votes"], start, end)),
            "app_alerts_same_place_72h": len(_in_window(ev["alerts"], start, end)),
            "government_alerts_same_place_72h": _gov_hits(gov, r.locality_name, start, end),
        })
    payload = {"total_reports_ever": total, "reports_shown": len(reports), "reports": reports}
    key = f"ai:trust:{dev}:{_fp(payload)}"

    def build():
        try:
            out, model = gemini.generate_json(TRUST_SYSTEM, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                              TRUST_SCHEMA, thinking="low")
        except gemini.GeminiError as exc:
            log.warning("Gemini trust scoring failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        label = out.get("label") if out.get("label") in LABELS else LABELS[0]
        return {"ok": True, "score": _clamp(out.get("score"), 0, 100), "label": label,
                "confirmed_accurate": _clamp(out.get("confirmed_accurate"), 0, len(reports)),
                "summary": str(out.get("summary") or "")[:160], "model": model, "scored_at": iso(utcnow())}

    res = cached_call(key, build, ok_ttl=current_app.config["GEMINI_TRUST_TTL"], fail_ttl=60, wait=40)
    if not res.get("ok"):
        return {**base, "ok": False, "score": None, "confirmed_accurate": None, "error": res.get("error")}

    row = db.session.get(TrustScore, dev)
    if row is None:
        row = TrustScore(device_id=dev, score=res["score"], reports_filed=total, confirmed_accurate=0)
        db.session.add(row)
    if (row.score, row.reports_filed, row.confirmed_accurate) != (res["score"], total, res["confirmed_accurate"]):
        row.score, row.reports_filed, row.confirmed_accurate = res["score"], total, res["confirmed_accurate"]
        db.session.commit()
    return {**base, **res}


def _weather_for(points: list[tuple[str, float, float]]) -> dict:
    app = current_app._get_current_object()
    out: dict[str, dict] = {}

    def work(p):
        name, lat, lon = p
        with app.app_context():
            try:
                s = weather.summarise(weather.fetch_forecast(lat, lon))
                out[name] = {"days_since_rain": s["past"]["days_since_rain"], "rain_7d_mm": s["past"]["rain_7d_mm"],
                             "rain_30d_mm": s["past"]["rain_30d_mm"], "forecast_next7_mm": s["next7_mm"],
                             "forecast_next3_mm": s["next3_mm"]}
            except (http.UpstreamError, ValueError, KeyError):
                pass

    if points:
        with ThreadPoolExecutor(max_workers=6) as ex:
            wait([ex.submit(work, p) for p in points], timeout=20)
    return out


def _collect_week() -> dict:
    now = utcnow()
    wk, prev = now - timedelta(days=7), now - timedelta(days=14)
    places: dict[str, dict] = {}

    def place(name: str) -> dict:
        k = gov_alerts.norm_area(name)
        return places.setdefault(k, {"place": (name or "").split(",")[0].strip(), "help_requests": 0,
                                     "critical": 0, "warning": 0, "watch": 0, "distinct_reporters": set(),
                                     "issues": defaultdict(int), "open": 0, "with_photo": 0, "samples": [],
                                     "last_week_help_requests": 0, "citizen_confirmations": 0, "app_alerts": 0,
                                     "government_alerts": 0, "government_events": [], "_ll": []})

    for r in SOSRequest.query.filter(SOSRequest.created_at >= prev).all():
        if not gov_alerts.norm_area(r.locality_name):
            continue
        p = place(r.locality_name)
        if r.created_at < wk:
            p["last_week_help_requests"] += 1
            continue
        p["help_requests"] += 1
        p[r.urgency.lower()] = p.get(r.urgency.lower(), 0) + 1
        p["distinct_reporters"].add(r.device_id)
        p["issues"][r.issue_type] += 1
        p["open"] += r.status != "Resolved"
        p["with_photo"] += bool(r.has_photo)
        if r.description and len(p["samples"]) < 3:
            p["samples"].append(r.description[:160])
        if r.lat is not None and r.lon is not None:
            p["_ll"].append((r.lat, r.lon))
    for v in Vote.query.filter(Vote.created_at >= wk).all():
        if gov_alerts.norm_area(v.locality_name):
            p = place(v.locality_name)
            p["citizen_confirmations"] += 1
            if v.lat is not None and v.lon is not None:
                p["_ll"].append((v.lat, v.lon))
    for a in Alert.query.filter(Alert.created_at >= wk, db.or_(Alert.category.is_(None), Alert.category != "Citizen reports")).all():
        if gov_alerts.norm_area(a.locality_name):
            place(a.locality_name)["app_alerts"] += 1
    for g in _gov_items():
        when = feeds.parse_dt(g.get("sent"))
        if not when or when < wk:
            continue
        for ar in dict.fromkeys(g.get("areas") or []):
            if gov_alerts.norm_area(ar):
                p = place(ar)
                p["government_alerts"] += 1
                ev = f"{g.get('title') or 'Alert'} ({g.get('severity') or 'Unknown'})"
                if ev not in p["government_events"] and len(p["government_events"]) < 3:
                    p["government_events"].append(ev[:120])

    rows = [p for p in places.values() if p["help_requests"] or p["citizen_confirmations"] or p["app_alerts"]
            or p["government_alerts"]]

    def weight(p):
        return (p["critical"] * 5 + p["warning"] * 3 + p["help_requests"] * 2 + p["citizen_confirmations"]
                + p["app_alerts"] * 2 + p["government_alerts"] * 2 + len(p["distinct_reporters"]) * 2)

    rows.sort(key=lambda p: (-weight(p), p["place"]))
    rows = rows[:25]
    pts = [(p["place"], sum(x for x, _ in p["_ll"]) / len(p["_ll"]), sum(y for _, y in p["_ll"]) / len(p["_ll"]))
           for p in rows if p["_ll"]][:6]
    wx = _weather_for(pts)
    clean = []
    for p in rows:
        d = {k: v for k, v in p.items() if not k.startswith("_")}
        d["distinct_reporters"] = len(p["distinct_reporters"])
        d["issues"] = dict(p["issues"])
        d = {k: v for k, v in d.items() if v not in (0, [], {}, "")}
        d["place"] = p["place"]
        if p["place"] in wx:
            d["measured_rainfall"] = wx[p["place"]]
        clean.append(d)
    return {"week_ending": now.date().isoformat(), "places": clean}


def risk_ticker() -> dict:
    if not gemini.configured():
        return {"ok": False, "error": "Gemini API key is not set", "items": []}
    return cached_call("ai:riskview", _risk_ticker, ok_ttl=120, fail_ttl=20, wait=50)


def _risk_ticker() -> dict:
    data = _collect_week()
    if not data["places"]:
        return {"ok": True, "items": [], "empty": True, "scored_at": iso(utcnow())}
    key = f"ai:risk:{_fp(data)}"
    known = {p["place"].lower(): p["place"] for p in data["places"]}

    def build():
        try:
            out, model = gemini.generate_json(RISK_SYSTEM, json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                              RISK_SCHEMA, thinking="low")
        except gemini.GeminiError as exc:
            log.warning("Gemini risk ticker failed: %s", exc)
            return {"ok": False, "error": str(exc), "items": []}
        items, seen = [], set()
        for it in out.get("items") or []:
            name = known.get(str(it.get("place") or "").strip().lower())
            if not name or name in seen:
                continue
            seen.add(name)
            items.append({"place": name, "score": _clamp(it.get("score"), 0, 100),
                          "level": it.get("level") if it.get("level") in LEVELS else "Watch",
                          "trend": it.get("trend") if it.get("trend") in TRENDS else "steady",
                          "reason": str(it.get("reason") or "")[:120]})
        items.sort(key=lambda x: -x["score"])
        return {"ok": True, "items": items[:5], "empty": not items, "model": model, "scored_at": iso(utcnow())}

    return cached_call(key, build, ok_ttl=current_app.config["GEMINI_RISK_TTL"], fail_ttl=60, wait=45)


TIPS_SYSTEM = (
    "You are the conservation advisor for WaterCast, a service for water-scarce regions, mostly in India. "
    "Write practical, hyperlocal water tips for residents of the one place described, based only on the live data "
    "given: measured and forecast rainfall, temperature and humidity, the derived risk tier, the season, citizen help "
    "requests from that place this week and official government alerts naming it. Every tip must be specific to "
    "these conditions (mention the actual numbers or the reported problem where useful), doable by an ordinary "
    "household, and safe. Cover storage, saving water, water safety, and what to do if heavy rain or contamination "
    "is involved, whichever fit the data. If citizens reported contamination, include boiling or purification advice. "
    "If heavy rain is forecast, include flood-safety and rainwater harvesting. Give 3 to 5 tips. title is 2 to 5 words. "
    "text is one or two plain sentences, at most 200 characters, no markdown."
)

TIPS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tips": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"title": {"type": "STRING"}, "text": {"type": "STRING"}},
                "required": ["title", "text"],
            },
        }
    },
    "required": ["tips"],
}


def conservation_tips(lat: float, lon: float, name: str, state: str = "", country: str = "") -> dict:
    if not gemini.configured():
        return {"ok": False, "error": "Gemini API key is not set", "tips": []}
    try:
        s = weather.summarise(weather.fetch_forecast(lat, lon))
    except (http.UpstreamError, ValueError, KeyError) as exc:
        msg = exc.describe() if isinstance(exc, http.UpstreamError) else "no weather data for this location"
        return {"ok": False, "error": f"Live weather unavailable - {msg}", "tips": []}

    now = utcnow()
    wk = now - timedelta(days=7)
    local = {"help_requests": 0, "issues": {}, "urgencies": {}, "samples": []}
    if name:
        for r in SOSRequest.query.filter(db.func.lower(SOSRequest.locality_name) == name.lower(),
                                         SOSRequest.created_at >= wk).all():
            local["help_requests"] += 1
            local["issues"][r.issue_type] = local["issues"].get(r.issue_type, 0) + 1
            local["urgencies"][r.urgency] = local["urgencies"].get(r.urgency, 0) + 1
            if r.description and len(local["samples"]) < 3:
                local["samples"].append(r.description[:160])
    gov = []
    if name:
        key = gov_alerts.norm_area(name)
        for g in _gov_items():
            when = feeds.parse_dt(g.get("sent"))
            if key and when and when >= wk and any(
                    key == gov_alerts.norm_area(a) or key in gov_alerts.norm_area(a) for a in g.get("areas") or []):
                gov.append(f"{g.get('title') or 'Alert'} ({g.get('severity') or 'Unknown'})"[:120])
                if len(gov) >= 4:
                    break

    cur = s["current"]
    payload = {
        "place": ", ".join(x for x in (name, state, country) if x) or f"{lat:.3f}, {lon:.3f}",
        "date": now.date().isoformat(), "month": now.strftime("%B"),
        "elevation_m": s.get("elevation_m"),
        "now": {"temp_c": cur.get("temp_c"), "humidity_pct": cur.get("humidity"), "condition": cur.get("condition"),
                "rain_now_mm": cur.get("precip_mm")},
        "rainfall": {"days_since_rain": s["past"]["days_since_rain"], "last_7_days_mm": s["past"]["rain_7d_mm"],
                     "last_30_days_mm": s["past"]["rain_30d_mm"], "next_3_days_mm": s["next3_mm"],
                     "next_7_days_mm": s["next7_mm"]},
        "forecast": [{"day": d["weekday"], "rain_chance_pct": d["precip_prob"], "rain_mm": d["precip_mm"],
                      "max_c": d["tmax"], "condition": d["condition"]} for d in s["daily"]],
        "derived": s["derived"],
        "citizen_reports_this_week": local,
        "government_alerts_this_week": gov,
    }
    fp_data = dict(payload)
    fp_data["now"] = {k: (round(v) if isinstance(v, (int, float)) else v) for k, v in payload["now"].items()}
    cache_key = f"ai:tips:{round(lat, 2)}:{round(lon, 2)}:{_fp(fp_data)}"

    def build():
        try:
            out, model = gemini.generate_json(TIPS_SYSTEM, json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                              TIPS_SCHEMA, thinking="minimal")
        except gemini.GeminiError as exc:
            log.warning("Gemini tips failed: %s", exc)
            return {"ok": False, "error": str(exc), "tips": []}
        tips = []
        for t in out.get("tips") or []:
            text = str(t.get("text") or "").strip()
            if text:
                tips.append({"title": str(t.get("title") or "").strip()[:60], "text": text[:260]})
        if not tips:
            return {"ok": False, "error": "Gemini returned no tips", "tips": []}
        return {"ok": True, "tips": tips[:5], "model": model, "scored_at": iso(utcnow())}

    return cached_call(cache_key, build, ok_ttl=current_app.config["GEMINI_TIPS_TTL"], fail_ttl=60, wait=45)
