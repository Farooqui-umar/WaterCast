from flask import jsonify, request

from ..errors import ApiError
from ..extensions import limiter
from ..services import ai_scores, http, places, weather
from ..validation import choice, clean_text, number
from . import bp


def _upstream(exc: http.UpstreamError, what: str) -> ApiError:
    return ApiError(502, f"Could not reach the {what} - {exc.describe()}.")


def _geocode_limit() -> str:
    return "30 per minute" if request.args.get("mode") == "search" else "120 per minute"


@bp.get("/geocode")
@limiter.limit(_geocode_limit)
def geocode():
    q = clean_text(request.args.get("q"), "q", max_len=100, required=True, min_len=2)
    mode = choice(request.args.get("mode"), "mode", ("suggest", "search"), default="suggest")
    try:
        return jsonify(places.lookup(q, mode))
    except http.UpstreamError as exc:
        raise _upstream(exc, "place-lookup service") from exc


@bp.get("/place")
@limiter.limit("60 per minute")
def place():
    lat = number(request.args.get("lat"), "lat", lo=-90, hi=90, required=True)
    lon = number(request.args.get("lon"), "lon", lo=-180, hi=180, required=True)
    name = clean_text(request.args.get("name"), "name", max_len=120)
    state = clean_text(request.args.get("state"), "state", max_len=120)
    country = clean_text(request.args.get("country"), "country", max_len=120)
    try:
        return jsonify(weather.place_summary(lat, lon, name, state, country))
    except http.UpstreamError as exc:
        raise _upstream(exc, "weather service") from exc
    except ValueError as exc:
        raise ApiError(502, "The weather service returned no data for this location.") from exc


@bp.get("/reverse")
@limiter.limit("30 per minute")
def reverse():
    lat = number(request.args.get("lat"), "lat", lo=-90, hi=90, required=True)
    lon = number(request.args.get("lon"), "lon", lo=-180, hi=180, required=True)
    out = dict(places.reverse(lat, lon))
    out.update({"lat": lat, "lon": lon, "nearest": None, "source": "OpenStreetMap contributors" if out["exact"] else None})
    return jsonify(out)


@bp.get("/tips")
@limiter.limit("30 per minute")
def tips():
    lat = number(request.args.get("lat"), "lat", lo=-90, hi=90, required=True)
    lon = number(request.args.get("lon"), "lon", lo=-180, hi=180, required=True)
    name = clean_text(request.args.get("name"), "name", max_len=120)
    state = clean_text(request.args.get("state"), "state", max_len=120)
    country = clean_text(request.args.get("country"), "country", max_len=120)
    return jsonify(ai_scores.conservation_tips(lat, lon, name, state, country))
