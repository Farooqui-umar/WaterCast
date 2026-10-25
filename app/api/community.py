from datetime import timedelta

from flask import jsonify
from sqlalchemy.exc import IntegrityError

from ..errors import ApiError
from ..extensions import db, limiter
from ..models import CommunityPost, PostReport
from ..security import audit, staff_required
from ..timeutil import utcnow
from ..validation import clean_text, device_id, json_body
from . import bp

MAX_POSTS_PER_DEVICE_PER_10_MIN = 5
HIDE_AFTER_REPORTS = 3


@bp.get("/community")
@limiter.limit("120 per minute")
def list_posts():
    rows = (CommunityPost.query.filter_by(hidden=False)
            .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc()).limit(60).all())
    return jsonify([r.to_dict() for r in rows])


@bp.post("/community")
@limiter.limit("20 per hour")
def create_post():
    data = json_body()
    text = clean_text(data.get("text"), "Your message", max_len=600, required=True)
    dev = device_id(data.get("device_id"))
    recent = CommunityPost.query.filter(CommunityPost.device_id == dev,
                                        CommunityPost.created_at >= utcnow() - timedelta(minutes=10)).all()
    if len(recent) >= MAX_POSTS_PER_DEVICE_PER_10_MIN:
        raise ApiError(429, "You're posting too fast - please wait a few minutes.")
    if any(r.text == text for r in recent):
        raise ApiError(400, "You already posted that.")
    post = CommunityPost(device_id=dev, author=clean_text(data.get("author"), "Name", max_len=40) or "Anonymous",
                         locality=clean_text(data.get("locality"), "Locality", max_len=80), text=text)
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict()), 201


@bp.post("/community/<int:post_id>/report")
@limiter.limit("30 per hour")
def report_post(post_id: int):
    post = db.session.get(CommunityPost, post_id)
    if post is None or post.hidden:
        raise ApiError(404, "Post not found.")
    reporter = device_id(json_body().get("device_id"))
    db.session.add(PostReport(post_id=post_id, reporter=reporter))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApiError(409, "You already reported this post.") from None
    post.report_count = PostReport.query.filter_by(post_id=post_id).count()
    if post.report_count >= HIDE_AFTER_REPORTS:
        post.hidden = True
    db.session.commit()
    return jsonify({"ok": True, "hidden": post.hidden})


@bp.delete("/community/<int:post_id>")
@staff_required()
def delete_post(post_id: int):
    row = db.session.get(CommunityPost, post_id)
    if row is None:
        raise ApiError(404, "Post not found.")
    snippet = row.text[:120]
    db.session.delete(row)
    db.session.commit()
    audit("community.delete", target=f"post:{post_id}", detail=snippet)
    return jsonify({"deleted": post_id})
