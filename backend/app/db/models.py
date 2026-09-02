"""
SQLAlchemy ORM 模型 — 对应 sql/schema.sql 十张表 + pgvector
SQLite 兼容版本（开发用）
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer,
    JSON, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import declarative_base, relationship

# pgvector 是可选依赖；未安装时把向量列退化为 JSONB(float 数组)，
# 此时精确相似度在 Python 端计算，SQL 端仅做持久化。
try:
    from pgvector.sqlalchemy import Vector
    VECTOR_DIM_DEFAULT = 512
    VectorColumn = Vector(VECTOR_DIM_DEFAULT)
    PGVECTOR_INSTALLED = True
except Exception:
    VectorColumn = JSON
    PGVECTOR_INSTALLED = False
    Vector = None

Base = declarative_base()


def _now():
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    purpose = Column(Text)
    data_policy = Column(Text)
    retention_days = Column(Integer, default=365)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=_now)

    subjects = relationship("Subject", back_populates="project",
                            cascade="all, delete-orphan")
    probes = relationship("ProbeImage", back_populates="project",
                          cascade="all, delete-orphan")
    access_grants = relationship("ProjectAccess", back_populates="project",
                                 cascade="all, delete-orphan")
    consents = relationship("ConsentRecord", back_populates="project",
                            cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False, default="reviewer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    access_grants = relationship("ProjectAccess", back_populates="user",
                                 cascade="all, delete-orphan")


class ProjectAccess(Base):
    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_project_access"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False, default="reviewer")
    created_at = Column(DateTime, nullable=False, default=_now)
    user = relationship("User", back_populates="access_grants")
    project = relationship("Project", back_populates="access_grants")


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True)
    consent_ref = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="valid")
    granted_at = Column(DateTime, nullable=False, default=_now)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)
    note = Column(Text)
    project = relationship("Project", back_populates="consents")
    subject = relationship("Subject")


class ThresholdProfile(Base):
    __tablename__ = "threshold_profiles"
    __table_args__ = (UniqueConstraint("project_id", name="uq_threshold_project"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    high = Column(Float, nullable=False, default=0.75)
    medium = Column(Float, nullable=False, default=0.60)
    low = Column(Float, nullable=False, default=0.45)
    source = Column(String(64), nullable=False, default="default_demo")
    sample_count = Column(Integer, nullable=False, default=0)
    calibrated_at = Column(DateTime)
    notes = Column(Text)
    project = relationship("Project")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("project_id", "external_code", name="uq_subj_project_code"),
        Index("idx_subjects_project", "project_id"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False)
    external_code = Column(String(64), nullable=False)
    display_name = Column(String(255))
    authorization_status = Column(String(32), default="authorized")
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=_now)

    project = relationship("Project", back_populates="subjects")
    reference_images = relationship("ReferenceImage", back_populates="subject",
                                    cascade="all, delete-orphan")
    candidates = relationship("MatchCandidate", back_populates="subject",
                              cascade="all, delete-orphan")


class ReferenceImage(Base):
    __tablename__ = "reference_images"
    __table_args__ = (Index("idx_ref_subject", "subject_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"),
                        nullable=False)
    object_uri = Column(String(1024), nullable=False)
    source_type = Column(String(32), default="authorized_upload")
    capture_session = Column(String(128))
    quality_score = Column(Float)
    consent_ref = Column(String(255))
    sha256 = Column(String(64))
    created_at = Column(DateTime, nullable=False, default=_now)

    subject = relationship("Subject", back_populates="reference_images")
    detections = relationship("FaceDetection", back_populates="reference_image",
                              cascade="all, delete-orphan")


class ProbeImage(Base):
    __tablename__ = "probe_images"
    __table_args__ = (
        Index("idx_probe_project", "project_id"),
        Index("idx_probe_status", "processing_status"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False)
    object_uri = Column(String(1024), nullable=False)
    source_type = Column(String(32), default="folder")
    capture_time = Column(DateTime)
    camera_id = Column(String(64))
    sha256 = Column(String(64))
    processing_status = Column(String(32), default="pending")
    error_message = Column(Text)
    processing_ms = Column(Integer)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=_now)

    project = relationship("Project", back_populates="probes")
    detections = relationship("FaceDetection", back_populates="probe_image",
                              cascade="all, delete-orphan")


class FaceDetection(Base):
    __tablename__ = "face_detections"
    __table_args__ = (
        Index("idx_det_probe", "probe_image_id"),
        Index("idx_det_ref", "reference_image_id"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    probe_image_id = Column(Integer,
                            ForeignKey("probe_images.id", ondelete="CASCADE"))
    reference_image_id = Column(Integer,
                                ForeignKey("reference_images.id", ondelete="CASCADE"))
    owner_type = Column(String(16), nullable=False)
    bbox = Column(JSON, nullable=False)
    landmarks = Column(JSON)
    detector_score = Column(Float)
    quality_score = Column(Float)
    blur_score = Column(Float)
    pose = Column(JSON)
    occlusion_score = Column(Float)
    usable = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    probe_image = relationship("ProbeImage", back_populates="detections")
    reference_image = relationship("ReferenceImage", back_populates="detections")
    match_candidates = relationship("MatchCandidate", back_populates="probe_face",
                                    cascade="all, delete-orphan")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        Index("idx_emb_owner", "owner_type", "owner_id"),
        Index("idx_emb_model", "model_version"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_type = Column(String(16), nullable=False)
    owner_id = Column(Integer, nullable=False)
    model_version = Column(String(64), nullable=False)
    vector = Column(VectorColumn, nullable=False)
    norm = Column(Float)
    created_at = Column(DateTime, nullable=False, default=_now)


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (
        Index("idx_cand_face", "probe_face_id"),
        Index("idx_cand_subject", "subject_id"),
        Index("idx_cand_status", "status"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    probe_face_id = Column(Integer,
                           ForeignKey("face_detections.id", ondelete="CASCADE"),
                           nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"),
                        nullable=False)
    similarity = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)
    decision_band = Column(String(16), default="low")
    status = Column(String(32), default="pending")
    review_id = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=_now)

    probe_face = relationship("FaceDetection", back_populates="match_candidates")
    subject = relationship("Subject", back_populates="candidates")


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (Index("idx_review_cand", "candidate_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer,
                          ForeignKey("match_candidates.id", ondelete="CASCADE"),
                          nullable=False)
    reviewer_id = Column(String(64))
    decision = Column(String(32))
    reason = Column(Text)
    evidence_uri = Column(String(1024))
    reviewed_at = Column(DateTime)

    candidate = relationship("MatchCandidate",
                              primaryjoin="ReviewTask.candidate_id == MatchCandidate.id")


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    version_tag = Column(String(64), unique=True, nullable=False)
    detector_name = Column(String(128))
    recognizer_name = Column(String(128))
    weights_hash = Column(String(64))
    preprocessing = Column(JSON)
    threshold_profile = Column(JSON)
    release_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=_now)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_name = Column(String(128), nullable=False)
    split_definition = Column(Text)
    model_version = Column(String(64), nullable=False)
    metrics_json = Column(JSON)
    status = Column(String(32), default="running")
    summary = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("idx_audit_action", "action"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(64))
    action = Column(String(64), nullable=False)
    resource = Column(String(256))
    meta_json = Column("metadata", JSON)
    created_at = Column(DateTime, nullable=False, default=_now)


# 后置 relationship 定义（解决非标准 FK 前向引用问题）
from sqlalchemy.orm import relationship as _sa_relationship

MatchCandidate.review = _sa_relationship(
    "ReviewTask",
    primaryjoin="foreign(MatchCandidate.review_id) == ReviewTask.id",
    uselist=False,
)
