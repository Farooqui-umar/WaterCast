from flask import current_app, jsonify, request

from ..extensions import limiter
from ..validation import clean_text
from ..services import gov_alerts, news
from . import bp


@bp.get("/news/alerts")
@limiter.limit("60 per minute")
def news_alerts():
    gov = gov_alerts.fetch_gov_alerts()
    hot = gov_alerts.compute_hot_areas(gov.get("items", []))
    feeds = current_app.config["SACHET_FEEDS"]
    return jsonify({"gov": {"ok": gov["ok"], "error": gov["error"], "detail": gov.get("detail", []),
                            "insecure_tls": gov.get("insecure_tls", False), "fetched_at": gov["fetched_at"],
                            "source": feeds[0] if feeds else "", "total": len(gov["items"]), "items": gov["items"][:40]},
                    "hot": hot})


@bp.get("/news/rainfall")
@limiter.limit("60 per minute")
def news_rainfall():
    return jsonify(news.rain_news())


@bp.get("/news/infrastructure")
@limiter.limit("60 per minute")
def news_infrastructure():
    return jsonify({"news": news.infra_news()})


@bp.get("/news/alert-coverage")
@limiter.limit("60 per minute")
def news_alert_coverage():
    event = clean_text(request.args.get("event"), "event", max_len=120)
    areas = [clean_text(a, "area", max_len=120) for a in request.args.getlist("area")[:6]]
    return jsonify(news.alert_coverage(event, [a for a in areas if a]))
