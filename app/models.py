from __future__ import annotations

from sqlalchemy import Index, func

from .extensions import db
from .timeutil import UTCDateTime, iso, utcnow


class User(db.Model):

    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="official")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_logins = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(UTCDateTime)
    last_login_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    def to_public(self) -> dict:
        return {"username": self.username, "role": self.role}


class SOSRequest(db.Model):
    __tablename__ = "sos_requests"
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False)
    locality_name = db.Column(db.String(120), nullable=False)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    issue_type = db.Column(db.String(60), nullable=False)
    urgency = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    has_photo = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_sos_locality_created", "locality_name", "created_at"),
        Index("ix_sos_device_created", "device_id", "created_at"),
        Index("ix_sos_created", "created_at"),
    )

    def to_dict(self) -> dict:
        return {"id": self.id, "locality_name": self.locality_name, "lat": self.lat, "lon": self.lon,
                "issue_type": self.issue_type, "urgency": self.urgency, "description": self.description,
                "has_photo": self.has_photo, "status": self.status, "created_at": iso(self.created_at)}


class Vote(db.Model):

    __tablename__ = "votes"
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=False)
    locality_name = db.Column(db.String(120), nullable=False)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_votes_locality_created", "locality_name", "created_at"),
        Index("ix_votes_created", "created_at"),
        Index("ix_votes_device_created", "device_id", "created_at"),
    )


class Alert(db.Model):

    __tablename__ = "alerts"
    id = db.Column(db.Integer, primary_key=True)
    locality_name = db.Column(db.String(120), nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(60))
    message = db.Column(db.Text)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_alerts_created", "created_at"),)


class TrustScore(db.Model):
    __tablename__ = "trust_scores"
    device_id = db.Column(db.String(64), primary_key=True)
    score = db.Column(db.Integer, nullable=False, default=55)
    reports_filed = db.Column(db.Integer, nullable=False, default=0)
    confirmed_accurate = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {"device_id": self.device_id, "score": self.score, "reports_filed": self.reports_filed,
                "confirmed_accurate": self.confirmed_accurate}


class CommunityPost(db.Model):
    __tablename__ = "community_posts"
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(80), nullable=False)
    author = db.Column(db.String(40))
    locality = db.Column(db.String(80))
    text = db.Column(db.Text, nullable=False)
    hidden = db.Column(db.Boolean, nullable=False, default=False)
    report_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_posts_visible_created", "hidden", "created_at"),
        Index("ix_posts_device_created", "device_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {"id": self.id, "author": self.author or "Anonymous", "locality": self.locality or "",
                "text": self.text, "created_at": iso(self.created_at)}


class PostReport(db.Model):

    __tablename__ = "post_reports"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    reporter = db.Column(db.String(120), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (db.UniqueConstraint("post_id", "reporter", name="uq_post_reporter"),)


class AuditEvent(db.Model):

    __tablename__ = "audit_events"
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    target = db.Column(db.String(120))
    detail = db.Column(db.String(500))
    ip = db.Column(db.String(64))
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (Index("ix_audit_created", "created_at"),)


Index("ix_sos_lower_locality_created", func.lower(SOSRequest.locality_name), SOSRequest.created_at)
Index("ix_votes_lower_locality_created", func.lower(Vote.locality_name), Vote.created_at)
Index("ix_alerts_lower_locality_created", func.lower(Alert.locality_name), Alert.created_at)
