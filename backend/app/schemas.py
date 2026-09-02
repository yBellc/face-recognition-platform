"""
FastAPI Pydantic 响应模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


# ------------------------------------------------------------
# 通用
# ------------------------------------------------------------
class OKResponse(BaseModel):
    ok: bool = True
    message: Optional[str] = None


class Paged(BaseModel):
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------
# 项目 / 人员 / 参考图
# ------------------------------------------------------------
class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    purpose: Optional[str] = None
    data_policy: Optional[str] = None
    retention_days: int = 365
    status: str
    created_at: datetime


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    external_code: str
    display_name: Optional[str] = None
    authorization_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class SubjectCreate(BaseModel):
    project_id: int
    external_code: str = Field(..., max_length=64)
    display_name: Optional[str] = None
    notes: Optional[str] = None


# ------------------------------------------------------------
# 待比对图片 + 检测
# ------------------------------------------------------------
class BBox(BaseModel):
    x: int; y: int; w: int; h: int; score: Optional[float] = None


class FaceDetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_type: str
    bbox: Dict[str, Any]
    # InsightFace 返回五点关键点数组 [[x, y], ...]；兼容历史字典格式。
    landmarks: Optional[Any] = None
    detector_score: Optional[float] = None
    quality_score: Optional[float] = None
    blur_score: Optional[float] = None
    pose: Optional[Dict[str, Any]] = None
    occlusion_score: Optional[float] = None
    usable: bool


class ProbeImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    object_uri: str
    source_type: str
    capture_time: Optional[datetime] = None
    camera_id: Optional[str] = None
    sha256: Optional[str] = None
    processing_status: str
    processing_ms: Optional[int] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    detections: List[FaceDetectionOut] = []


class ProbeUploadResponse(BaseModel):
    probe_id: int
    task_id: Optional[str] = None
    status: str
    sha256: str
    object_uri: str


# ------------------------------------------------------------
# 候选 + 复核
# ------------------------------------------------------------
class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    probe_id: int
    probe_face_id: int
    subject_id: int
    subject_code: Optional[str] = None
    similarity: float
    rank: int
    decision_band: str
    status: str
    review_task_id: Optional[int] = None
    created_at: Optional[datetime] = None


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(confirm|exclude|uncertain)$")
    reason: Optional[str] = None
    reviewer_id: Optional[str] = None
    evidence_uri: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    candidate_id: int
    reviewer_id: Optional[str] = None
    decision: Optional[str] = None
    reason: Optional[str] = None
    reviewed_at: Optional[datetime] = None


# ------------------------------------------------------------
# 仪表盘
# ------------------------------------------------------------
class DashboardStats(BaseModel):
    today_probe_images: int = 0
    today_faces_detected: int = 0
    pending_review_tasks: int = 0
    avg_processing_ms: float = 0.0
    fmr_estimate: Optional[float] = None
    current_model_version: Optional[str] = None


# ------------------------------------------------------------
# 流水线输出（任务完成后的结果摘要）
# ------------------------------------------------------------
class ProcessedFace(BaseModel):
    detection_id: int
    bbox: Dict[str, Any]
    quality_score: Optional[float] = None
    usable: bool
    candidates: List[CandidateOut] = []


class ProcessingSummary(BaseModel):
    probe_id: int
    image: str
    num_faces: int
    faces: List[ProcessedFace] = []
    processing_ms: int = 0
    error: Optional[str] = None
