from datetime import datetime, timezone

from sqlalchemy import JSON, Float, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc)


class Room(Base):
    __tablename__ = 'rooms'
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    phase: Mapped[str] = mapped_column(String(20), default='lobby')
    instructor_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Participant(Base):
    __tablename__ = 'participants'
    __table_args__ = (UniqueConstraint('room_code', 'nickname'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'))
    nickname: Mapped[str] = mapped_column(String(24))
    team: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Assignment(Base):
    __tablename__ = 'assignments'
    __table_args__ = (UniqueConstraint('participant_id', 'post_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey('participants.id'))
    post_id: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    label: Mapped[str | None] = mapped_column(String(6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# Additive tables: existing Milestone 1 rooms/labels are preserved on upgrade.
class RoomRules(Base):
    __tablename__ = 'room_rules'
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSON)


class TeamAccount(Base):
    __tablename__ = 'team_accounts'
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'), primary_key=True)
    team: Mapped[int] = mapped_column(Integer, primary_key=True)
    balance: Mapped[int] = mapped_column(Integer)
    annotation_packs: Mapped[int] = mapped_column(Integer, default=0)
    audit_enabled: Mapped[bool] = mapped_column(default=False)
    compute_packs: Mapped[int] = mapped_column(Integer, default=0)
    upgraded: Mapped[bool] = mapped_column(default=False)
    configuration: Mapped[str] = mapped_column(String(30), default='word')


class Purchase(Base):
    __tablename__ = 'purchases'
    __table_args__ = (UniqueConstraint('room_code', 'team', 'request_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'))
    team: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey('participants.id'))
    action: Mapped[str] = mapped_column(String(30))
    cost: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditDecision(Base):
    __tablename__ = 'audit_decisions'
    __table_args__ = (UniqueConstraint('room_code', 'team', 'post_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'))
    team: Mapped[int] = mapped_column(Integer)
    post_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey('participants.id'))
    label: Mapped[str | None] = mapped_column(String(6), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TrainingRun(Base):
    __tablename__ = 'training_runs'
    __table_args__ = (UniqueConstraint('room_code', 'team', 'request_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'))
    team: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[str] = mapped_column(String(30))
    training_ms: Mapped[float] = mapped_column(Float)
    electricity: Mapped[float] = mapped_column(Float)
    water: Mapped[float] = mapped_column(Float)
    snapshot: Mapped[dict] = mapped_column(JSON)
    artifact: Mapped[dict] = mapped_column(JSON)
    evaluation: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RoomExperience(Base):
    """Additive session metadata, safe for rooms created before Milestone 4."""
    __tablename__ = 'room_experiences'
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'), primary_key=True)
    demo: Mapped[bool] = mapped_column(default=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    elapsed_before_pause: Mapped[float] = mapped_column(Float, default=0)


class ClassroomDecision(Base):
    """Additive ledger and site selection; legacy team accounts stay unchanged."""
    __tablename__ = 'classroom_decisions'
    room_code: Mapped[str] = mapped_column(ForeignKey('rooms.code'), primary_key=True)
    team: Mapped[int] = mapped_column(Integer, primary_key=True)
    representative_id: Mapped[int | None] = mapped_column(ForeignKey('participants.id'), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('participants.id'), nullable=True)
    choice: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_credits: Mapped[int] = mapped_column(Integer, default=0)
    profile: Mapped[str] = mapped_column(String(16), default='air')
