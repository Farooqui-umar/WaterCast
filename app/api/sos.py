from datetime import timedelta

from flask import jsonify, request

from ..errors import ApiError
from ..extensions import db, limiter
from ..models import Alert, SOSRequest, TrustScore, Vote
from ..security import audit, current_user, staff_required
from ..services import ai_scores
from ..timeutil import utcnow
from ..validation import choice, clean_text, device_id, json_body, number, query_int
from . import bp

ISSUE_TYPES = ("No Water Supply", "Contaminated Water", "Tanker Delay", "Pipeline Burst", "Other")
URGENCIES = ("Watch", "Warning", "Critical")
STATUSES = ("Pending", "In Progress", "Resolved")
TRUST_BASE = 50
MAX_SOS_PER_DEVICE_PER_HOUR = 5


def _public_view(row: SOSRequest) -> dict:
    return {"id": row.id, "locality_name": row.locality_name, "issue_type": row.issue_type, "urgency": row.urgency,
            "status": row.status, "has_photo": row.has_photo, "created_at": row.created_at.isoformat()}


@bp.post("/sos")
@limiter.limit("20 per hour")
def create_sos():
    data = json_body()
    dev = device_id(data.get("device_id"))
    locality = clean_text(data.get("locality_name"), "locality_name", max_len=120, required=True)
    issue = choice(data.get("issue_type"), "issue_type", ISSUE_TYPES)
    urgency = choice(data.get("urgency"), "urgency", URGENCIES)
    description = clean_text(data.get("description"), "description", max_len=1000)
    lat = number(data.get("lat"), "lat", lo=-90, hi=90)
    lon = number(data.get("lon"), "lon", lo=-180, hi=180)
    has_photo = bool(data.get("has_photo", False))

    since = utcnow() - timedelta(hours=1)
    recent = SOSRequest.query.filter(SOSRequest.device_id == dev, SOSRequest.created_at >= since).count()
    if recent >= MAX_SOS_PER_DEVICE_PER_HOUR:
        raise ApiError(429, "You have sent several requests in the last hour. Please wait before sending another.")

    sos = SOSRequest(device_id=dev, locality_name=locality, lat=lat, lon=lon, issue_type=issue, urgency=urgency,
                     description=description, has_photo=has_photo, status="Pending")
    db.session.add(sos)
    trust = db.session.get(TrustScore, dev)
    if trust is None:
        trust = TrustScore(device_id=dev, score=TRUST_BASE, reports_filed=0, confirmed_accurate=0)
        db.session.add(trust)
    trust.reports_filed += 1
    if urgency == "Critical":
        db.session.add(Alert(locality_name=locality, severity="Critical", category="Citizen reports",
                             message=f"New citizen SOS: {issue} reported as Critical in {locality}."))
    db.session.commit()
    ai_scores.invalidate_trust(dev)
    return jsonify({"sos": _public_view(sos), "trust": trust.to_dict()}), 201


@bp.get("/sos")
@limiter.limit("120 per minute")
def list_sos():
    q = SOSRequest.query
    locality = clean_text(request.args.get("locality"), "locality", max_len=120)
    if locality:
        q = q.filter(db.func.lower(SOSRequest.locality_name) == locality.lower())
    limit = query_int("limit", 20, lo=1, hi=100)
    rows = q.order_by(SOSRequest.created_at.desc(), SOSRequest.id.desc()).limit(limit).all()
    if current_user() is not None:
        return jsonify([r.to_dict() for r in rows])
    return jsonify([_public_view(r) for r in rows])


@bp.patch("/sos/<int:sos_id>")
@staff_required()
def update_sos(sos_id: int):
    row = db.session.get(SOSRequest, sos_id)
    if row is None:
        raise ApiError(404, "Request not found.")
    status = choice(json_body().get("status"), "status", STATUSES)
    old, row.status = row.status, status
    db.session.commit()
    ai_scores.invalidate_trust(row.device_id)
    audit("sos.status", target=f"sos:{sos_id}", detail=f"{old} -> {status}")
    return jsonify(row.to_dict())


@bp.get("/sos/top")
@limiter.limit("120 per minute")
def sos_top():
    days = query_int("days", 7, lo=1, hi=90)
    n = db.func.count(SOSRequest.id)
    rows = (db.session.query(SOSRequest.locality_name, n).filter(SOSRequest.created_at >= utcnow() - timedelta(days=days))
            .group_by(SOSRequest.locality_name).order_by(n.desc()).limit(5).all())
    return jsonify([{"locality": r[0], "count": r[1]} for r in rows])


@bp.post("/vote")
@limiter.limit("30 per hour")
def create_vote():
    data = json_body()
    dev = device_id(data.get("device_id"))
    locality = clean_text(data.get("locality_name"), "locality_name", max_len=120, required=True)
    since = utcnow() - timedelta(hours=24)
    if Vote.query.filter(Vote.device_id == dev, db.func.lower(Vote.locality_name) == locality.lower(),
                         Vote.created_at >= since).first():
        raise ApiError(409, "You already confirmed this shortage today.")
    db.session.add(Vote(device_id=dev, locality_name=locality, lat=number(data.get("lat"), "lat", lo=-90, hi=90),
                        lon=number(data.get("lon"), "lon", lo=-180, hi=180)))
    db.session.commit()
    count = Vote.query.filter(db.func.lower(Vote.locality_name) == locality.lower()).count()
    return jsonify({"ok": True, "locality_vote_count": count}), 201


@bp.get("/trust/<device>")
@limiter.limit("60 per minute")
def get_trust(device: str):
    return jsonify(ai_scores.trust_for_device(device_id(device)))


@bp.get("/risk/ticker")
@limiter.limit("60 per minute")
def risk_ticker():
    return jsonify(ai_scores.risk_ticker())
