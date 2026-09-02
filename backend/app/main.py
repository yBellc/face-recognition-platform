"""
FastAPI 应用主入口
路由：
  - /health, /dashboard          —— 方案第七部分：首页仪表盘
  - /api/v1/projects             —— 项目管理
  - /api/v1/subjects             —— 匿名人员管理
  - /api/v1/references           —— 参考照片上传 + 特征注册
  - /api/v1/probes               —— 待比对图片上传 / 查询 / 处理
  - /api/v1/candidates           —— 候选列表
  - /api/v1/reviews              —— 人工复核
  - /api/v1/evaluation           —— 评测数据入口
"""
from __future__ import annotations

import hashlib
import base64
import csv
import hmac
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np

from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status,
    Response, Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from PIL import Image
from io import BytesIO
from io import StringIO

from app.config import get_settings
from app.db.models import (
    AuditLog, Embedding, EvaluationRun, FaceDetection, MatchCandidate,
    ModelVersion, ProbeImage, ReferenceImage, ReviewTask, Subject, Project,
    User, ProjectAccess, ConsentRecord, ThresholdProfile,
)
from app.db.session import get_session, session_scope, HAS_PSYCOPG
from app import schemas
from app.services.pipeline import build_gallery_from_db, process_probe, register_reference_image, _log_audit
from app.services.storage import get_storage


settings = get_settings()

if settings.environment.lower() == "production":
    if not HAS_PSYCOPG:
        raise RuntimeError("生产环境必须安装 psycopg 并连接 PostgreSQL，禁止使用 SQLite")
    insecure_defaults = []
    if settings.db_password == "postgres": insecure_defaults.append("FACE_DB_PASSWORD")
    if settings.minio_access_key == "minioadmin": insecure_defaults.append("FACE_MINIO_ACCESS_KEY")
    if settings.minio_secret_key == "minioadmin": insecure_defaults.append("FACE_MINIO_SECRET_KEY")
    if os.getenv("FACE_ADMIN_PASSWORD", "") in {"", "admin123"}: insecure_defaults.append("FACE_ADMIN_PASSWORD")
    if any(origin.startswith(("http://localhost", "http://127.0.0.1")) for origin in settings.cors_origin_list):
        insecure_defaults.append("FACE_CORS_ORIGINS")
    if insecure_defaults:
        raise RuntimeError("生产环境仍使用演示配置，请先设置: " + ", ".join(insecure_defaults))

app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    description="基于 InsightFace + pgvector 的人脸识别候选检索与人工复核系统",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

_auth_secret = os.getenv("FACE_AUTH_SECRET", "")
if settings.environment.lower() == "production" and not _auth_secret:
    raise RuntimeError("生产环境必须设置 FACE_AUTH_SECRET")
AUTH_SECRET = (_auth_secret or "local-demo-secret-change-before-deploy").encode()
AUTH_TTL_SECONDS = 8 * 60 * 60

# 登录失败保护。生产环境应在网关再加一层限流，这里的应用层限制用于防止
# 单实例部署或开发环境被暴力尝试；成功登录会清除对应窗口。
_login_failures: dict[str, deque[float]] = defaultdict(deque)


def _login_rate_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.lower()}"


def _login_rate_limited(key: str) -> int:
    now = time.time()
    bucket = _login_failures[key]
    window = max(30, int(settings.auth_rate_limit_window_seconds))
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    limit = max(1, int(settings.auth_rate_limit_attempts))
    if len(bucket) < limit:
        return 0
    return max(1, int(window - (now - bucket[0])))


def _record_login_failure(key: str) -> None:
    _login_failures[key].append(time.time())


def _clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)


def _validate_image_upload(file: UploadFile, data: bytes) -> str:
    """限制图片类型、大小并做真实解码校验，避免把任意文件写入对象存储。"""
    max_bytes = max(1, int(settings.max_upload_mb)) * 1024 * 1024
    if not data:
        raise HTTPException(400, "上传文件为空")
    if len(data) > max_bytes:
        raise HTTPException(413, f"图片不能超过 {settings.max_upload_mb}MB")
    allowed = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if content_type not in allowed and ext not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(415, "仅支持 JPG、PNG 或 WebP 图片")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("unsupported format")
            image.verify()
    except Exception:
        raise HTTPException(400, "图片文件损坏或格式无效")
    return allowed.get(content_type, "jpg" if ext in {"", "jpeg"} else ext)


def _password_hash(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180_000).hex()
    return f"pbkdf2_sha256$180000${salt}${digest}"


def _password_ok(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return scheme == "pbkdf2_sha256" and hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _issue_token(user: User) -> str:
    payload = {"uid": user.id, "username": user.username, "role": user.role,
               "exp": int(time.time()) + AUTH_TTL_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _token_payload(token: str) -> Optional[dict]:
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except Exception:
        return None


PUBLIC_PATHS = {"/health", "/api/v1/auth/login", "/docs", "/openapi.json", "/redoc"}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS or not request.url.path.startswith("/api/v1/"):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    # <img> 标签无法附加 Authorization；仅对受保护的媒体预览允许短期令牌查询参数。
    if not token and request.method == "GET" and any(x in request.url.path for x in ("/preview", "/thumb", "/crop")):
        token = request.query_params.get("access_token", "")
    payload = _token_payload(token) if token else None
    if payload is None:
        return JSONResponse({"detail": "请先登录"}, status_code=401)
    request.state.user = payload
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/v1/") and request.url.path != "/api/v1/auth/login":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def current_user(request: Request, session: Session = Depends(get_session)) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "请先登录")
    # 每次受保护请求重新读取账号状态和角色，管理员停用账号或收回权限后，
    # 不必等待旧令牌自然过期即可生效。
    row = session.get(User, int(user.get("uid", 0)))
    if row is None or not row.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    user["username"] = row.username
    user["role"] = row.role
    return user


def _require_project_access(project_id: int, session: Session, user: dict, write: bool = False) -> None:
    """Enforce project-level isolation for every protected project operation."""
    if user.get("role") == "admin":
        return
    grant = session.scalar(select(ProjectAccess).filter(
        ProjectAccess.user_id == int(user.get("uid", 0)),
        ProjectAccess.project_id == project_id,
    ))
    if grant is None or (write and grant.role not in {"admin", "operator"}):
        raise HTTPException(403, "当前账号没有该项目的访问权限")


# ----------------------------------------------------------------
# 通用：健康检查
# ----------------------------------------------------------------
@app.get("/health", tags=["system"])
def health():
    return {
        "healthy": True,
        "latency": 0,
        "details": {
            "model_version": {
                "tag": settings.default_model_version,
                "provider": "insightface",
            },
            "db_url": settings.database_url.split("@")[-1],
        },
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/auth/login", tags=["auth"])
def login(payload: dict, request: Request, session: Session = Depends(get_session)):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    rate_key = _login_rate_key(request, username)
    retry_after = _login_rate_limited(rate_key)
    if retry_after:
        raise HTTPException(429, "登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    user = session.scalar(select(User).filter(User.username == username))
    if not user or not user.is_active or not _password_ok(password, user.password_hash):
        _record_login_failure(rate_key)
        raise HTTPException(401, "用户名或密码错误")
    _clear_login_failures(rate_key)
    _log_audit(session, username, "auth.login", f"user:{user.id}")
    session.commit()
    return {"access_token": _issue_token(user), "token_type": "bearer",
            "user": {"id": user.id, "username": user.username, "role": user.role}}


@app.get("/api/v1/auth/me", tags=["auth"])
def auth_me(user: dict = Depends(current_user)):
    return user


@app.post("/api/v1/auth/password", tags=["auth"])
def change_password(payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    row = session.get(User, int(user.get("uid", 0)))
    if row is None or not _password_ok(str(payload.get("old_password", "")), row.password_hash):
        raise HTTPException(400, "原密码不正确")
    new_password = str(payload.get("new_password", ""))
    if len(new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    row.password_hash = _password_hash(new_password)
    _log_audit(session, row.username, "auth.password.change", f"user:{row.id}")
    session.commit()
    return {"ok": True}


@app.get("/api/v1/admin/users", tags=["auth"])
def list_users(session: Session = Depends(get_session), user: dict = Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可管理账号")
    rows = session.scalars(select(User).order_by(User.id)).all()
    return [{"id": r.id, "username": r.username, "role": r.role, "is_active": r.is_active,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "project_ids": [g.project_id for g in r.access_grants]} for r in rows]


@app.post("/api/v1/admin/users", tags=["auth"])
def create_user(payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可创建账号")
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "reviewer")).strip().lower()
    if not username or len(password) < 8:
        raise HTTPException(400, "账号不能为空，密码至少 8 位")
    if role not in {"admin", "operator", "reviewer"}:
        raise HTTPException(400, "角色只能是 admin、operator 或 reviewer")
    if session.scalar(select(User).filter(User.username == username)):
        raise HTTPException(409, "账号已存在")
    row = User(username=username, password_hash=_password_hash(password), role=role)
    session.add(row); session.flush()
    project_ids = payload.get("project_ids") or []
    for pid in project_ids:
        if session.get(Project, int(pid)):
            session.add(ProjectAccess(user_id=row.id, project_id=int(pid), role=role))
    _log_audit(session, user.get("username", "admin"), "user.create", f"user:{row.id}", {"role": role})
    session.commit(); session.refresh(row)
    return {"id": row.id, "username": row.username, "role": row.role, "project_ids": [g.project_id for g in row.access_grants]}


@app.patch("/api/v1/admin/users/{user_id}", tags=["auth"])
def update_user(user_id: int, payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """管理员更新账号启停、角色和项目授权；所有变更写入审计日志。"""
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可管理账号")
    row = session.get(User, user_id)
    if row is None:
        raise HTTPException(404, "账号不存在")
    if "is_active" in payload:
        active = payload.get("is_active")
        if not isinstance(active, bool):
            raise HTTPException(400, "is_active 必须是布尔值")
        if user_id == int(user.get("uid", 0)) and not active:
            raise HTTPException(400, "不能停用当前登录账号")
        row.is_active = active
    if "role" in payload:
        role = str(payload.get("role", "")).strip().lower()
        if role not in {"admin", "operator", "reviewer"}:
            raise HTTPException(400, "角色只能是 admin、operator 或 reviewer")
        row.role = role
        # 未显式传项目列表时，保持项目范围不变，仅同步授权角色。
        session.query(ProjectAccess).filter(ProjectAccess.user_id == user_id).update({"role": role})
    if "project_ids" in payload:
        project_ids = payload.get("project_ids") or []
        if not isinstance(project_ids, list):
            raise HTTPException(400, "project_ids 必须是数组")
        normalized = sorted({int(pid) for pid in project_ids})
        existing = {p.id for p in session.scalars(select(Project).filter(Project.id.in_(normalized))).all()} if normalized else set()
        if existing != set(normalized):
            raise HTTPException(400, "project_ids 中包含不存在的项目")
        session.query(ProjectAccess).filter(ProjectAccess.user_id == user_id).delete(synchronize_session=False)
        for pid in normalized:
            session.add(ProjectAccess(user_id=user_id, project_id=pid, role=row.role))
    _log_audit(session, user.get("username", "admin"), "user.update", f"user:{row.id}", {
        "is_active": row.is_active, "role": row.role,
        "project_ids": [g.project_id for g in row.access_grants],
    })
    session.commit(); session.refresh(row)
    return {"id": row.id, "username": row.username, "role": row.role,
            "is_active": row.is_active, "project_ids": [g.project_id for g in row.access_grants]}


@app.get("/api/v1/projects/{project_id}/thresholds", tags=["governance"])
def get_thresholds(project_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user)
    profile = session.scalar(select(ThresholdProfile).filter(ThresholdProfile.project_id == project_id))
    if profile is None:
        return {"project_id": project_id, "high": settings.threshold_high, "medium": settings.threshold_medium,
                "low": settings.threshold_low, "source": "default_demo", "sample_count": 0,
                "calibrated_at": None, "notes": "尚未使用授权数据校准"}
    return {"project_id": project_id, "high": profile.high, "medium": profile.medium, "low": profile.low,
            "source": profile.source, "sample_count": profile.sample_count,
            "calibrated_at": profile.calibrated_at.isoformat() if profile.calibrated_at else None,
            "notes": profile.notes}


@app.get("/api/v1/projects/{project_id}/policy", tags=["governance"])
def get_project_policy(project_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user)
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")
    return {"project_id": project.id, "retention_days": project.retention_days,
            "data_policy": project.data_policy or "", "purpose": project.purpose or ""}


@app.put("/api/v1/projects/{project_id}/policy", tags=["governance"])
def update_project_policy(project_id: int, payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user, write=True)
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")
    try:
        days = int(payload.get("retention_days", project.retention_days))
    except Exception:
        raise HTTPException(400, "保留期限必须是整数天数")
    if days < 1 or days > 3650:
        raise HTTPException(400, "保留期限应为 1～3650 天")
    project.retention_days = days
    project.data_policy = str(payload.get("data_policy") or "")[:2000]
    _log_audit(session, user.get("username", "user"), "project.policy.update", f"project:{project_id}", {"retention_days": days})
    session.commit()
    return get_project_policy(project_id, session=session, user=user)


@app.put("/api/v1/projects/{project_id}/thresholds", tags=["governance"])
def update_thresholds(project_id: int, payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user, write=True)
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "项目不存在")
    try:
        high, medium, low = float(payload["high"]), float(payload["medium"]), float(payload["low"])
    except Exception:
        raise HTTPException(400, "high、medium、low 必须是数字")
    if not (0 < low < medium < high < 1):
        raise HTTPException(400, "阈值必须满足 0 < low < medium < high < 1")
    profile = session.scalar(select(ThresholdProfile).filter(ThresholdProfile.project_id == project_id))
    if profile is None:
        profile = ThresholdProfile(project_id=project_id)
        session.add(profile)
    profile.high, profile.medium, profile.low = high, medium, low
    profile.source = str(payload.get("source") or "manual_calibration")
    profile.sample_count = int(payload.get("sample_count") or 0)
    profile.calibrated_at = datetime.utcnow()
    profile.notes = str(payload.get("notes") or "")[:2000]
    _log_audit(session, user.get("username", "user"), "threshold.update", f"project:{project_id}",
               {"high": high, "medium": medium, "low": low, "sample_count": profile.sample_count})
    session.commit(); session.refresh(profile)
    return get_thresholds(project_id, session=session, user=user)


@app.get("/api/v1/projects/{project_id}/consents", tags=["governance"])
def list_consents(project_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user)
    rows = session.scalars(select(ConsentRecord).filter(ConsentRecord.project_id == project_id).order_by(ConsentRecord.id.desc())).all()
    return [{"id": r.id, "project_id": r.project_id, "subject_id": r.subject_id, "consent_ref": r.consent_ref,
             "status": r.status, "granted_at": r.granted_at.isoformat() if r.granted_at else None,
             "expires_at": r.expires_at.isoformat() if r.expires_at else None, "note": r.note} for r in rows]


@app.post("/api/v1/projects/{project_id}/consents", tags=["governance"])
def create_consent(project_id: int, payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user, write=True)
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "项目不存在")
    ref = str(payload.get("consent_ref", "")).strip()
    if not ref:
        raise HTTPException(400, "授权凭证编号不能为空")
    expires = None
    if payload.get("expires_at"):
        try: expires = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception: raise HTTPException(400, "expires_at 格式应为 ISO 日期时间")
    row = ConsentRecord(project_id=project_id, subject_id=payload.get("subject_id"), consent_ref=ref,
                        expires_at=expires, note=str(payload.get("note") or "")[:2000])
    session.add(row)
    _log_audit(session, user.get("username", "user"), "consent.create", f"project:{project_id}", {"consent_ref": ref})
    session.commit(); session.refresh(row)
    return {"id": row.id, "project_id": project_id, "consent_ref": row.consent_ref, "status": row.status,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None}


@app.post("/api/v1/consents/{consent_id}/revoke", tags=["governance"])
def revoke_consent(consent_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """登记授权撤回，不直接抹掉证据；后续由保留策略预览/清理任务执行删除并留痕。"""
    row = session.get(ConsentRecord, consent_id)
    if row is None:
        raise HTTPException(404, "授权记录不存在")
    _require_project_access(row.project_id, session, user, write=True)
    if row.status == "revoked":
        return {"ok": True, "id": row.id, "status": row.status}
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    _log_audit(session, user.get("username", "user"), "consent.revoke", f"consent:{row.id}", {"project_id": row.project_id})
    session.commit()
    return {"ok": True, "id": row.id, "status": row.status, "revoked_at": row.revoked_at.isoformat()}


@app.get("/api/v1/audit-logs", tags=["governance"])
def list_audit_logs(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """只读审计查询；没有提供修改/删除审计记录的接口。"""
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可查看完整审计日志")
    rows = session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [{"id": r.id, "actor": r.actor, "action": r.action, "resource": r.resource,
             "metadata": r.meta_json, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@app.get("/api/v1/monitoring/summary", tags=["monitoring"])
def monitoring_summary(session: Session = Depends(get_session), user: dict = Depends(current_user)):
    stmt = select(ProbeImage).order_by(ProbeImage.id.desc()).limit(200)
    if user.get("role") != "admin":
        stmt = stmt.filter(ProbeImage.project_id.in_(select(ProjectAccess.project_id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))))
    rows = session.scalars(stmt).all()
    processed = [r for r in rows if r.processing_status == "processed" and r.processing_ms is not None]
    latencies = sorted(int(r.processing_ms) for r in processed)
    p95 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * .95) - 1))] if latencies else None
    p99 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * .99) - 1))] if latencies else None
    processed_count = sum(r.processing_status == "processed" for r in rows)
    failed_count = sum(r.processing_status == "failed" for r in rows)
    return {"window": "最近 200 张", "total": len(rows), "processed": processed_count,
            "failed": failed_count, "failure_rate": failed_count / len(rows) if rows else 0,
            "queued": sum(r.processing_status in {"pending", "processing"} for r in rows),
            "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
            "latency_p95_ms": p95, "latency_p99_ms": p99,
            "model_version": settings.default_model_version}


@app.get("/api/v1/monitoring/queue", tags=["monitoring"])
def monitoring_queue(session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """检查 Redis/Celery 队列和数据库积压，供部署探针和运行监控使用。"""
    stmt = select(ProbeImage).filter(ProbeImage.processing_status.in_({"pending", "processing"}))
    if user.get("role") != "admin":
        stmt = stmt.filter(ProbeImage.project_id.in_(select(ProjectAccess.project_id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))))
    db_queued = len(session.scalars(stmt).all())
    redis_ok = False
    redis_error = None
    workers = []
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        redis_ok = bool(client.ping())
        if redis_ok:
            from app.workers.celery_app import celery_app
            pongs = celery_app.control.inspect(timeout=1).ping() or {}
            workers = sorted(pongs.keys())
    except Exception as exc:
        redis_error = str(exc)[:180]
    return {"redis_ok": redis_ok, "workers": workers, "worker_count": len(workers),
            "db_queued": db_queued, "queue_ready": redis_ok and bool(workers),
            "error": redis_error, "model_version": settings.default_model_version}


def _retention_probe_rows(session: Session, user: dict, project_id: Optional[int] = None):
    """返回按项目保留期限已到期的探针；只处理已归档记录，避免清掉待复核证据。"""
    if user.get("role") not in {"admin", "operator"}:
        raise HTTPException(403, "仅管理员或操作员可执行数据保留清理")
    projects_stmt = select(Project).order_by(Project.id)
    if project_id is not None:
        _require_project_access(project_id, session, user, write=True)
        projects_stmt = projects_stmt.filter(Project.id == project_id)
    elif user.get("role") != "admin":
        projects_stmt = projects_stmt.join(ProjectAccess, ProjectAccess.project_id == Project.id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))
    rows = []
    for project in session.scalars(projects_stmt).unique().all():
        cutoff = datetime.utcnow() - timedelta(days=max(1, int(project.retention_days or 365)))
        probes = session.scalars(select(ProbeImage).filter(
            ProbeImage.project_id == project.id,
            ProbeImage.archived_at.is_not(None),
            ProbeImage.archived_at < cutoff,
        )).all()
        rows.extend((project, probe, cutoff) for probe in probes)
    return rows


@app.post("/api/v1/maintenance/retention", tags=["governance"])
def retention_cleanup(payload: Optional[dict] = None, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """按项目 retention_days 清理已归档探针；默认 dry_run，便于接入定时任务前先预览。"""
    payload = payload or {}
    project_value = payload.get("project_id")
    project_id = int(project_value) if project_value not in (None, "") else None
    dry_run = bool(payload.get("dry_run", True))
    rows = _retention_probe_rows(session, user, project_id)
    if dry_run:
        return {"dry_run": True, "count": len(rows), "items": [
            {"project_id": p.id, "probe_id": probe.id, "archived_at": probe.archived_at.isoformat(), "cutoff": cutoff.isoformat()}
            for p, probe, cutoff in rows
        ]}
    storage = get_storage()
    deleted = 0
    for project, probe, _cutoff in rows:
        object_uri = probe.object_uri
        det_ids = [d.id for d in session.scalars(select(FaceDetection).filter(FaceDetection.probe_image_id == probe.id)).all()]
        if det_ids:
            cand_ids = [c.id for c in session.scalars(select(MatchCandidate).filter(MatchCandidate.probe_face_id.in_(det_ids))).all()]
            if cand_ids:
                session.query(ReviewTask).filter(ReviewTask.candidate_id.in_(cand_ids)).delete(synchronize_session=False)
                session.query(MatchCandidate).filter(MatchCandidate.id.in_(cand_ids)).delete(synchronize_session=False)
            session.query(Embedding).filter(Embedding.owner_type == "probe", Embedding.owner_id.in_(det_ids)).delete(synchronize_session=False)
            session.query(FaceDetection).filter(FaceDetection.id.in_(det_ids)).delete(synchronize_session=False)
        session.delete(probe)
        storage.delete_object(object_uri)
        deleted += 1
    _log_audit(session, user.get("username", "user"), "retention.cleanup", f"project:{project_id or 'all'}", {"deleted": deleted})
    session.commit()
    return {"dry_run": False, "deleted": deleted}


@app.get("/api/v1/export/candidates.csv", tags=["export"])
def export_candidates(project_id: Optional[int] = Query(None), probe_id: Optional[int] = Query(None), session: Session = Depends(get_session), user: dict = Depends(current_user)):
    stmt = select(FaceDetection, ProbeImage).join(ProbeImage, ProbeImage.id == FaceDetection.probe_image_id).order_by(FaceDetection.id.desc())
    if project_id is not None:
        _require_project_access(project_id, session, user, write=False)
        stmt = stmt.filter(ProbeImage.project_id == project_id)
    if probe_id is not None:
        probe = session.get(ProbeImage, probe_id)
        if not probe: raise HTTPException(404, "图片记录不存在")
        _require_project_access(probe.project_id, session, user, write=False)
        stmt = stmt.filter(ProbeImage.id == probe_id)
    output = StringIO(); writer = csv.writer(output)
    writer.writerow(["候选ID", "图片ID", "人脸ID", "对象编号", "相似度", "决策带", "复核状态", "处理时间", "模型版本"])
    export_rows = 0
    for face, probe in session.execute(stmt).all():
        candidates = session.scalars(select(MatchCandidate).filter(MatchCandidate.probe_face_id == face.id).order_by(MatchCandidate.rank)).all()
        if not candidates:
            # 把未达到阈值/无法判断的人脸也纳入导出，领导能看到“检测到了但没有强行匹配”。
            writer.writerow(["", probe.id, face.id, "", "", "rejected", "uncertain", probe.created_at.isoformat() if probe.created_at else "", settings.default_model_version])
            export_rows += 1
            continue
        for cand in candidates:
            subject = session.get(Subject, cand.subject_id)
            writer.writerow([cand.id, probe.id, face.id, subject.external_code if subject else "", f"{cand.similarity:.4f}", cand.decision_band, cand.status, probe.created_at.isoformat() if probe.created_at else "", settings.default_model_version])
            export_rows += 1
    content = output.getvalue().encode("utf-8-sig")
    scope = f"probe:{probe_id}" if probe_id is not None else f"project:{project_id or 'all'}"
    _log_audit(session, user.get("username", "user"), "result.export", scope, {"rows": export_rows})
    session.commit()
    return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=recognition-results.csv"})


# ----------------------------------------------------------------
# 首页仪表盘
# ----------------------------------------------------------------
@app.get("/api/v1/dashboard", tags=["dashboard"])
def dashboard(session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """DB 不可用时返回零值，不报 500；返回前端期望的完整结构"""
    try:
        allowed_projects = None if user.get("role") == "admin" else select(ProjectAccess.project_id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))
        probe_scope = [] if allowed_projects is None else [ProbeImage.project_id.in_(allowed_projects)]
        candidate_scope = [] if allowed_projects is None else [ProbeImage.project_id.in_(allowed_projects)]
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        today_probes = session.scalar(
            select(func.count()).select_from(ProbeImage)
            .filter(ProbeImage.created_at >= today_start, *probe_scope)
        ) or 0
        today_faces = session.scalar(
            select(func.count()).select_from(FaceDetection)
            .join(ProbeImage, ProbeImage.id == FaceDetection.probe_image_id)
            .filter(ProbeImage.created_at >= today_start, *probe_scope)
        ) or 0
        pending = session.scalar(
            select(func.count()).select_from(MatchCandidate)
            .join(FaceDetection, FaceDetection.id == MatchCandidate.probe_face_id)
            .join(ProbeImage, ProbeImage.id == FaceDetection.probe_image_id)
            .filter(MatchCandidate.status == "pending", *candidate_scope)
        ) or 0
        avg_ms = session.scalar(
            select(func.avg(ProbeImage.processing_ms))
            .filter(ProbeImage.processing_status == "processed", *probe_scope)
        ) or 0.0
        mv_tag = session.scalar(
            select(ModelVersion.version_tag)
            .order_by(ModelVersion.id.desc()).limit(1)
        ) or settings.default_model_version
        # 决策带分布
        band_base = select(func.count()).select_from(MatchCandidate).join(FaceDetection, FaceDetection.id == MatchCandidate.probe_face_id).join(ProbeImage, ProbeImage.id == FaceDetection.probe_image_id)
        band_high = session.scalar(band_base.filter(MatchCandidate.decision_band == "high", *candidate_scope)) or 0
        band_med = session.scalar(band_base.filter(MatchCandidate.decision_band == "medium", *candidate_scope)) or 0
        band_low = session.scalar(band_base.filter(MatchCandidate.decision_band == "low", *candidate_scope)) or 0
        band_rej = session.scalar(band_base.filter(MatchCandidate.decision_band == "rejected", *candidate_scope)) or 0
        # 最近探针
        recent_rows = session.execute(
            select(ProbeImage).filter(*probe_scope).order_by(ProbeImage.id.desc()).limit(8)
        ).scalars().all()
        recent_probes = [
            {
                "id": r.id, "project_id": r.project_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "processing_status": r.processing_status,
                "processing_ms": r.processing_ms,
                "candidate_count": session.scalar(
                    select(func.count()).select_from(MatchCandidate)
                    .join(FaceDetection, FaceDetection.id == MatchCandidate.probe_face_id)
                    .filter(FaceDetection.probe_image_id == r.id)
                ) or 0,
            }
            for r in recent_rows
        ]
        # 项目概览
        proj_stmt = select(Project).limit(20)
        if allowed_projects is not None: proj_stmt = proj_stmt.filter(Project.id.in_(allowed_projects))
        proj_rows = session.execute(proj_stmt).scalars().all()
        project_summary = [
            {
                "project_id": p.id, "project_name": p.name,
                "subjects": session.scalar(select(func.count()).select_from(Subject).filter(Subject.project_id == p.id)) or 0,
                # ReferenceImage 通过 Subject 归属项目，不能直接读取不存在的 project_id 字段。
                "references": session.scalar(
                    select(func.count()).select_from(ReferenceImage)
                    .join(Subject, Subject.id == ReferenceImage.subject_id)
                    .filter(Subject.project_id == p.id)
                ) or 0,
                "probes_today": session.scalar(
                    select(func.count()).select_from(ProbeImage)
                    .filter(ProbeImage.project_id == p.id, ProbeImage.created_at >= today_start)
                ) or 0,
            }
            for p in proj_rows
        ]
    except Exception:
        today_probes = today_faces = pending = 0
        avg_ms = 0.0
        mv_tag = settings.default_model_version
        band_high = band_med = band_low = band_rej = 0
        recent_probes = []
        project_summary = []
    return {
        "probe_image_count_today": int(today_probes),
        "face_detected_count_today": int(today_faces),
        "candidate_pending_review": int(pending),
        "avg_processing_ms_today": float(avg_ms),
        "model_version": {"tag": mv_tag, "decision_band": "high"},
        "thresholds": {"high": settings.threshold_high, "medium": settings.threshold_medium, "low": settings.threshold_low},
        "band_counts": {"high": int(band_high), "medium": int(band_med), "low": int(band_low), "rejected": int(band_rej)},
        "project_summary": project_summary,
        "recent_probes": recent_probes,
    }


# ----------------------------------------------------------------
# 项目
# ----------------------------------------------------------------
@app.get("/api/v1/projects", response_model=List[schemas.ProjectOut], tags=["projects"])
def list_projects(session: Session = Depends(get_session), user: dict = Depends(current_user)):
    stmt = select(Project).order_by(Project.id)
    if user.get("role") != "admin":
        stmt = stmt.join(ProjectAccess, ProjectAccess.project_id == Project.id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))
    return session.scalars(stmt).unique().all()


@app.post("/api/v1/projects", response_model=schemas.ProjectOut, tags=["projects"])
def create_project(name: str = Form(...),
                   purpose: Optional[str] = Form(None),
                   data_policy: Optional[str] = Form(None),
                   retention_days: int = Form(365),
                   session: Session = Depends(get_session), user: dict = Depends(current_user)):
    if user.get("role") not in {"admin", "operator"}:
        raise HTTPException(403, "当前账号不能创建项目")
    p = Project(name=name, purpose=purpose, data_policy=data_policy,
                retention_days=retention_days)
    session.add(p)
    session.flush()
    # 创建者必须立即拥有新项目的访问权，否则操作员创建成功后会在项目列表中看不到，
    # 也无法继续录入对象或上传图片。管理员通过全局权限访问，普通创建者按自身角色授权。
    if user.get("role") != "admin":
        session.add(ProjectAccess(user_id=int(user.get("uid", 0)), project_id=p.id, role=user.get("role", "operator")))
    _log_audit(session, user.get("username", "user"), "project.create", f"project:{p.id}", {"name": p.name})
    session.commit(); session.refresh(p)
    return p


@app.delete("/api/v1/projects/{project_id}", tags=["projects"])
def delete_project(project_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user, write=True)
    """删除项目及其对象库、识别记录和本地/对象存储文件。"""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "项目不存在")

    # 先收集并清理向量与对象文件；SQLAlchemy relationship cascade 负责其余关联表。
    subjects = list(project.subjects)
    probes = list(project.probes)
    object_uris = [r.object_uri for subject in subjects for r in subject.reference_images]
    object_uris.extend(p.object_uri for p in probes)
    subject_ids = [s.id for s in subjects]
    if subject_ids:
        session.execute(delete(Embedding).where(Embedding.owner_type == "subject", Embedding.owner_id.in_(subject_ids)))
    for uri in object_uris:
        get_storage().delete_object(uri)
    _log_audit(session, "operator", "project.delete", f"project:{project_id}",
               {"name": project.name, "subjects": len(subjects), "probes": len(probes)})
    session.delete(project)
    session.commit()
    return {"deleted": True, "project_id": project_id}


# ----------------------------------------------------------------
# 匿名人员
# ----------------------------------------------------------------
@app.get("/api/v1/projects/{project_id}/subjects",
         response_model=List[schemas.SubjectOut], tags=["subjects"])
def list_subjects(project_id: int, q: Optional[str] = None,
                  limit: int = 100, offset: int = 0,
                  session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(project_id, session, user)
    stmt = select(Subject).filter(Subject.project_id == project_id)
    if q:
        stmt = stmt.filter(Subject.external_code.ilike(f"%{q}%"))
    stmt = stmt.order_by(Subject.id.desc()).limit(limit).offset(offset)
    return session.scalars(stmt).all()


@app.get("/api/v1/subjects", response_model=List[schemas.SubjectOut], tags=["subjects"])
def list_subjects_legacy(project_id: int = Query(...), q: Optional[str] = None,
                         limit: int = 100, offset: int = 0,
                         session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """Compatibility endpoint used by the dataset management page."""
    return list_subjects(project_id=project_id, q=q, limit=limit,
                         offset=offset, session=session, user=user)


@app.post("/api/v1/subjects", response_model=schemas.SubjectOut, tags=["subjects"])
def create_subject(payload: schemas.SubjectCreate,
                   session: Session = Depends(get_session), user: dict = Depends(current_user)):
    _require_project_access(payload.project_id, session, user, write=True)
    s = Subject(**payload.model_dump())
    session.add(s); session.commit(); session.refresh(s)
    return s


@app.post("/api/v1/subjects/batch", response_model=List[schemas.SubjectOut], tags=["subjects"])
def create_subjects_batch(payload: dict, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """Create anonymous test subjects in one request; no mock fallback."""
    project_id = payload.get("project_id")
    items = payload.get("items") or []
    if not isinstance(project_id, int) or not items:
        raise HTTPException(400, "project_id 和 items 不能为空")
    _require_project_access(project_id, session, user, write=True)
    created = []
    for item in items:
        code = str(item.get("external_code", "")).strip()
        if not code:
            continue
        subject = Subject(project_id=project_id, external_code=code,
                          display_name=item.get("display_name"))
        session.add(subject)
        created.append(subject)
    if not created:
        raise HTTPException(400, "没有有效的 external_code")
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(400, f"批量创建失败：{exc}")
    for subject in created:
        session.refresh(subject)
    return created


@app.delete("/api/v1/subjects/{subject_id}", tags=["subjects"])
def delete_subject(subject_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "人员不存在")
    _require_project_access(subject.project_id, session, user, write=True)
    # 显式清理无外键关联的向量、复核任务和对象存储文件。仅依赖 ORM
    # cascade 会在存在 review_tasks 时留下外键冲突，也会留下孤儿文件。
    refs = session.scalars(select(ReferenceImage).filter(ReferenceImage.subject_id == subject_id)).all()
    ref_uris = [r.object_uri for r in refs]
    ref_ids = [r.id for r in refs]
    if ref_ids:
        ref_det_ids = [d.id for d in session.scalars(
            select(FaceDetection).filter(FaceDetection.reference_image_id.in_(ref_ids))
        ).all()]
        if ref_det_ids:
            session.query(Embedding).filter(
                Embedding.owner_type == "reference",
                Embedding.owner_id.in_(ref_det_ids),
            ).delete(synchronize_session=False)
            session.query(FaceDetection).filter(
                FaceDetection.id.in_(ref_det_ids)
            ).delete(synchronize_session=False)
        session.query(ReferenceImage).filter(
            ReferenceImage.id.in_(ref_ids)
        ).delete(synchronize_session=False)

    candidates = session.scalars(
        select(MatchCandidate).filter(MatchCandidate.subject_id == subject_id)
    ).all()
    candidate_ids = [c.id for c in candidates]
    if candidate_ids:
        session.query(ReviewTask).filter(
            ReviewTask.candidate_id.in_(candidate_ids)
        ).delete(synchronize_session=False)
        session.query(MatchCandidate).filter(
            MatchCandidate.id.in_(candidate_ids)
        ).delete(synchronize_session=False)

    session.query(Subject).filter(Subject.id == subject_id).delete(synchronize_session=False)
    for uri in ref_uris:
        get_storage().delete_object(uri)
    _log_audit(session, actor="user", action="delete_subject",
               resource=f"subject/{subject_id}",
               metadata={"references_deleted": len(ref_ids), "candidates_deleted": len(candidate_ids)})
    session.commit()
    return {"ok": True, "deleted_id": subject_id,
            "references_deleted": len(ref_ids), "candidates_deleted": len(candidate_ids)}


# ----------------------------------------------------------------
# 参考图上传 + 自动入库（特征）
# ----------------------------------------------------------------
@app.post("/api/v1/references/upload", tags=["references"])
def upload_reference(
    project_id: int = Form(...),
    external_code: str = Form(..., min_length=1, max_length=64),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: dict = Depends(current_user),
):
    _require_project_access(project_id, session, user, write=True)
    data = file.file.read()
    ext = _validate_image_upload(file, data)
    res = register_reference_image(
        session=session, project_id=project_id,
        external_code=external_code, image_bytes=data, file_ext=ext,
    )
    session.commit()
    if not res:
        raise HTTPException(404, "项目不存在")
    if "error" in res:
        raise HTTPException(400, detail=res["error"])
    return {"ok": True, **res}


@app.post("/api/v1/references/folder-upload", tags=["references"])
def upload_reference_folder(
    project_id: int = Form(...),
    files: List[UploadFile] = File(...),
    folder_names: List[str] = Form(default=[]),
    session: Session = Depends(get_session),
    user: dict = Depends(current_user),
):
    """按文件夹批量注册参考图：一个顶层文件夹对应一个重点关注对象。

    folder_names 与 files 按位置对应，由浏览器的 webkitRelativePath 提供。
    每个对象允许只有 1 张图片；无效图片只记录错误，不影响同批次其他文件。
    """
    if not files:
        raise HTTPException(400, "至少选择一张图片")
    _require_project_access(project_id, session, user, write=True)
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "项目不存在")
    if folder_names and len(folder_names) != len(files):
        raise HTTPException(400, "文件夹信息与图片数量不一致，请重新选择文件夹")

    results = []
    created_subject_ids = set()
    for index, file in enumerate(files):
        folder = (folder_names[index] if folder_names else "").strip()
        if not folder:
            parts = Path(file.filename or "").parts
            folder = parts[0] if len(parts) > 1 else "未命名对象"
        # 兼容旧客户端传入完整相对路径，只使用图片所在的最后一级目录名。
        folder_parts = [part for part in folder.replace("\\", "/").split("/") if part]
        folder = folder_parts[-1] if folder_parts else "未命名对象"
        folder = folder.replace("/", "_").replace("\\", "_").strip()[:64] or "未命名对象"
        before = session.query(Subject).filter(
            Subject.project_id == project_id,
            Subject.external_code == folder,
        ).first()
        data = file.file.read()
        try:
            ext = _validate_image_upload(file, data)
        except HTTPException as exc:
            results.append({"filename": file.filename, "folder": folder, "error": exc.detail})
            continue
        res = register_reference_image(
            session=session, project_id=project_id,
            external_code=folder, image_bytes=data, file_ext=ext,
            source_type="folder_upload",
        )
        if before is None and res and res.get("subject_id"):
            created_subject_ids.add(res["subject_id"])
        results.append({"filename": file.filename, "folder": folder, **(res or {"error": "项目不存在"})})

    # 全是无效图片的文件夹不留下空对象。
    for subject_id in created_subject_ids:
        has_reference = session.query(ReferenceImage).filter(
            ReferenceImage.subject_id == subject_id
        ).first()
        if has_reference is None:
            subject = session.get(Subject, subject_id)
            if subject is not None:
                session.delete(subject)
    session.commit()
    succeeded = sum(1 for item in results if not item.get("error") and item.get("reference_image_id"))
    return {
        "project_id": project_id,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


# ----------------------------------------------------------------
# Probe 上传 + 查询
# ----------------------------------------------------------------
@app.post("/api/v1/probes/upload", response_model=schemas.ProbeUploadResponse,
          tags=["probes"])
def upload_probe(
    project_id: int = Form(...),
    source_type: str = Form("folder"),
    camera_id: Optional[str] = Form(None),
    capture_time: Optional[datetime] = Form(None),
    file: UploadFile = File(...),
    async_mode: bool = Form(False, description="True=用 Celery 异步处理，False=同步处理"),
    session: Session = Depends(get_session),
    user: dict = Depends(current_user),
):
    """
    1. 上传到对象存储
    2. 写 probe_images（status=pending）
    3. 按模式触发 pipeline
    """
    _require_project_access(project_id, session, user, write=True)
    data = file.file.read()
    ext = _validate_image_upload(file, data)
    digest = hashlib.sha256(data).hexdigest()
    key = f"{project_id}/{digest[:8]}_{int(time.time()*1000)}.{ext}"

    storage = get_storage()
    uri = storage.put_object(
        settings.minio_bucket_probe, key, data,
        content_type=f"image/{ext}",
    )

    probe = ProbeImage(
        project_id=project_id, object_uri=uri, source_type=source_type,
        capture_time=capture_time, camera_id=camera_id, sha256=digest,
        processing_status="pending",
    )
    session.add(probe); session.flush()
    probe_id = probe.id
    session.commit()  # 必须先 commit，独立 session 才能读到

    task_id = None
    if async_mode:
        try:
            from app.workers.celery_app import enqueue_process_probe
            task_id = enqueue_process_probe(probe.id)
        except Exception as e:
            probe.processing_status = "failed"
            probe.error_message = f"任务队列不可用: {str(e)[:300]}"
            session.commit()
            get_storage().delete_object(uri)
            raise HTTPException(503, "任务队列暂不可用，请检查 Redis/Celery 后重试")
    else:
        with session_scope() as s2:
            result = process_probe(s2, probe_id)
        # 从数据库刷新 probe 状态（process_probe 在独立 session 中修改）
        session.refresh(probe)
        if result.get("status") == "failed":
            probe.error_message = result.get("error")

    session.commit()
    session.refresh(probe)
    return schemas.ProbeUploadResponse(
        probe_id=probe.id,
        task_id=task_id,
        status=probe.processing_status,
        sha256=digest,
        object_uri=uri,
    )


@app.get("/api/v1/probes/list", tags=["probes"])
def list_probes_alias(project_id: Optional[int] = Query(None),
                       status: Optional[str] = Query(None),
                       include_archived: bool = Query(False),
                       limit: int = 20, offset: int = 0,
                       session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """别名路由，供前端 /probes/list 使用"""
    return list_probes(project_id=project_id, status=status, include_archived=include_archived,
                       limit=limit, offset=offset, session=session, user=user)


@app.get("/api/v1/probes/{probe_id}", response_model=schemas.ProbeImageOut,
         tags=["probes"])
def get_probe(probe_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "probe 不存在")
    _require_project_access(probe.project_id, session, user)
    # SQLAlchemy 查询关联
    probe.detections  # lazy load
    return probe


@app.get("/api/v1/probes", response_model=List[schemas.ProbeImageOut],
         tags=["probes"])
def list_probes(project_id: Optional[int] = Query(None),
                status: Optional[str] = Query(None),
                include_archived: bool = Query(False),
                limit: int = 50, offset: int = 0,
                session: Session = Depends(get_session), user: dict = Depends(current_user)):
    if project_id is not None:
        _require_project_access(project_id, session, user)
    stmt = select(ProbeImage)
    if project_id is None and user.get("role") != "admin":
        stmt = stmt.join(ProjectAccess, ProjectAccess.project_id == ProbeImage.project_id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))
    if project_id is not None:
        stmt = stmt.filter(ProbeImage.project_id == project_id)
    if not include_archived:
        stmt = stmt.filter(ProbeImage.archived_at.is_(None))
    if status is not None:
        stmt = stmt.filter(ProbeImage.processing_status == status)
    stmt = stmt.order_by(ProbeImage.id.desc()).limit(limit).offset(offset)
    return session.scalars(stmt).unique().all()


@app.post("/api/v1/probes/{probe_id}/archive", tags=["probes"])
def archive_probe(probe_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "probe 不存在")
    _require_project_access(probe.project_id, session, user, write=True)
    probe.archived_at = datetime.utcnow()
    _log_audit(session, user.get("username", "user"), "probe.archive", f"probe:{probe_id}")
    session.commit()
    return {"ok": True, "probe_id": probe_id, "archived_at": probe.archived_at.isoformat()}


@app.delete("/api/v1/probes/{probe_id}", tags=["probes"])
def delete_probe(probe_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """删除已归档探针及其检测/候选记录。先归档再删除，避免误删待复核证据。"""
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "探针图片不存在")
    _require_project_access(probe.project_id, session, user, write=True)
    if probe.archived_at is None:
        raise HTTPException(400, "请先归档图片，再执行删除")
    object_uri = probe.object_uri
    session.delete(probe)
    _log_audit(session, user.get("username", "user"), "probe.delete", f"probe:{probe_id}")
    session.commit()
    # 数据库删除成功后再尝试删除本地文件；文件不存在不影响结果。
    try:
        path = Path(object_uri.replace("file://", ""))
        if path.is_file():
            path.unlink()
    except Exception:
        pass
    return {"ok": True, "probe_id": probe_id}


@app.post("/api/v1/probes/{probe_id}/reprocess", tags=["probes"])
def reprocess_probe(probe_id: int,
                    async_mode: bool = Form(False),
                    session: Session = Depends(get_session), user: dict = Depends(current_user)):
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404)
    _require_project_access(probe.project_id, session, user, write=True)
    probe.processing_status = "pending"
    probe.error_message = None
    session.flush()
    task_id = None
    if async_mode:
        try:
            from app.workers.celery_app import enqueue_process_probe
            task_id = enqueue_process_probe(probe_id)
        except Exception as e:
            raise HTTPException(500, f"celery 投递失败: {e}")
    else:
        with session_scope() as s2:
            r = process_probe(s2, probe_id)
            return r
    session.commit()
    return {"ok": True, "task_id": task_id}


# ----------------------------------------------------------------
# 候选 + 人工复核
# ----------------------------------------------------------------
def _cand_to_out(c: MatchCandidate, session: Session) -> schemas.CandidateOut:
    subj = session.get(Subject, c.subject_id)
    # 查 probe_id
    probe_id = 0
    try:
        fd = session.get(FaceDetection, c.probe_face_id)
        if fd:
            probe_id = fd.probe_image_id or 0
    except Exception:
        pass
    return schemas.CandidateOut(
        id=c.id, probe_id=probe_id, probe_face_id=c.probe_face_id,
        subject_id=c.subject_id,
        subject_code=subj.external_code if subj else None,
        similarity=c.similarity, rank=c.rank,
        decision_band=c.decision_band, status=c.status,
        review_task_id=c.review_id,
        created_at=c.created_at,
    )


@app.get("/api/v1/candidates", response_model=List[schemas.CandidateOut],
         tags=["candidates"])
def list_candidates(project_id: Optional[int] = Query(None),
                    probe_id: Optional[int] = Query(None),
                    status: Optional[str] = Query(None),
                    band: Optional[str] = Query(None),
                    limit: int = 100, offset: int = 0,
                    session: Session = Depends(get_session), user: dict = Depends(current_user)):
    if project_id is not None:
        _require_project_access(project_id, session, user)
    stmt = (
        select(MatchCandidate)
        .join(FaceDetection, FaceDetection.id == MatchCandidate.probe_face_id)
        .join(ProbeImage, ProbeImage.id == FaceDetection.probe_image_id)
    )
    if project_id is None and user.get("role") != "admin":
        stmt = stmt.filter(ProbeImage.project_id.in_(select(ProjectAccess.project_id).filter(ProjectAccess.user_id == int(user.get("uid", 0)))))
    if project_id is not None:
        stmt = stmt.filter(ProbeImage.project_id == project_id)
    if probe_id is not None:
        stmt = stmt.filter(ProbeImage.id == probe_id)
    if status is not None:
        stmt = stmt.filter(MatchCandidate.status == status)
    if band is not None:
        stmt = stmt.filter(MatchCandidate.decision_band == band)
    stmt = stmt.order_by(MatchCandidate.id.desc()).limit(limit).offset(offset)
    return [_cand_to_out(c, session)
            for c in session.scalars(stmt).unique().all()]


@app.post("/api/v1/candidates/{candidate_id}/review",
          response_model=schemas.ReviewOut, tags=["reviews"])
def review_candidate(candidate_id: int,
                     body: schemas.ReviewRequest,
                     session: Session = Depends(get_session), user: dict = Depends(current_user)):
    cand = session.get(MatchCandidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "candidate 不存在")
    face = session.get(FaceDetection, cand.probe_face_id)
    probe = session.get(ProbeImage, face.probe_image_id) if face else None
    if probe is None:
        raise HTTPException(404, "关联图片不存在")
    _require_project_access(probe.project_id, session, user, write=True)
    # 创建或更新 review
    review = session.scalar(
        select(ReviewTask).filter(ReviewTask.candidate_id == candidate_id)
    ) or ReviewTask(candidate_id=candidate_id)
    review.reviewer_id = body.reviewer_id or "web"
    review.decision = body.decision
    review.reason = body.reason
    review.evidence_uri = body.evidence_uri
    review.reviewed_at = datetime.now(timezone.utc)
    session.add(review); session.flush()

    # 同步更新 candidate.status
    mapping = {"confirm": "confirmed", "exclude": "excluded",
               "uncertain": "uncertain"}
    cand.status = mapping.get(body.decision, cand.status)
    cand.review_id = review.id
    session.add(AuditLog(actor=review.reviewer_id,
                         action=f"review_{body.decision}",
                         resource=f"candidate/{candidate_id}",
                         meta_json={"reason": body.reason}))
    session.commit(); session.refresh(review)
    return review


# ----------------------------------------------------------------
# 评测数据写入接口
# ----------------------------------------------------------------
@app.post("/api/v1/evaluation/runs", tags=["evaluation"])
def create_eval_run(dataset_name: str = Form(...),
                    model_version: str = Form(...),
                    split_definition: Optional[str] = Form(None),
                    metrics_file: UploadFile = File(None),
                    session: Session = Depends(get_session)):
    import json as _json
    data = None
    if metrics_file is not None:
        try:
            raw = metrics_file.file.read()
            data = _json.loads(raw)
        except Exception:
            data = {"raw": raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    completed = data is not None
    run = EvaluationRun(dataset_name=dataset_name, model_version=model_version,
                        split_definition=split_definition, metrics_json=data,
                        status="success" if completed else "running",
                        started_at=now, completed_at=now if completed else None)
    session.add(run); session.commit(); session.refresh(run)
    return {"ok": True, "id": run.id}


# ----------------------------------------------------------------
# 启动提示
# ----------------------------------------------------------------
# ----------------------------------------------------------------
# 参考图查询 + 缩略图
# ----------------------------------------------------------------
@app.get("/api/v1/subjects/{subject_id}/references", tags=["references"])
def list_subject_references(subject_id: int,
                             session: Session = Depends(get_session), user: dict = Depends(current_user)):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "人员不存在")
    _require_project_access(subject.project_id, session, user)
    refs = session.scalars(
        select(ReferenceImage)
        .filter(ReferenceImage.subject_id == subject_id)
        .order_by(ReferenceImage.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "subject_id": r.subject_id,
            "quality_score": r.quality_score,
            "object_uri": r.object_uri,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in refs
    ]


@app.delete("/api/v1/references/{ref_id}", tags=["references"])
def delete_reference(ref_id: int, session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """删除一张错误/过期参考图及其人脸特征，不影响同一人员的其他参考图。"""
    ref = session.get(ReferenceImage, ref_id)
    if ref is None:
        raise HTTPException(404, "参考图不存在")
    subject_id = ref.subject_id
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "人员不存在")
    _require_project_access(subject.project_id, session, user, write=True)
    uri = ref.object_uri
    det_ids = [d.id for d in session.scalars(
        select(FaceDetection).filter(FaceDetection.reference_image_id == ref_id)
    ).all()]
    if det_ids:
        session.query(Embedding).filter(
            Embedding.owner_type == "reference",
            Embedding.owner_id.in_(det_ids),
        ).delete(synchronize_session=False)
        session.query(FaceDetection).filter(
            FaceDetection.id.in_(det_ids)
        ).delete(synchronize_session=False)
    session.delete(ref)
    session.flush()
    get_storage().delete_object(uri)
    _log_audit(session, actor="user", action="delete_reference",
               resource=f"reference/{ref_id}",
               metadata={"subject_id": subject_id})
    session.commit()
    return {"ok": True, "deleted_id": ref_id, "subject_id": subject_id}


@app.get("/api/v1/references/{ref_id}/thumb", tags=["references"])
def reference_thumbnail(ref_id: int,
                         session: Session = Depends(get_session), user: dict = Depends(current_user)):
    ref = session.get(ReferenceImage, ref_id)
    if ref is None:
        raise HTTPException(404, "参考图不存在")
    subject = session.get(Subject, ref.subject_id)
    if subject is None:
        raise HTTPException(404, "人员不存在")
    _require_project_access(subject.project_id, session, user)
    storage = get_storage()
    data = storage.get_object(ref.object_uri)
    if data is None:
        raise HTTPException(404, "图片文件不存在")
    return StreamingResponse(BytesIO(data), media_type="image/jpeg")


@app.post("/api/v1/subjects/{subject_id}/re-embed", tags=["subjects"])
def re_embed_subject(subject_id: int,
                     session: Session = Depends(get_session), user: dict = Depends(current_user)):
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(404, "人员不存在")
    _require_project_access(subject.project_id, session, user, write=True)
    from app.services.pipeline import re_embed_subject
    try:
        re_embed_subject(session, subject_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ----------------------------------------------------------------
# Probe 预览 + 人脸裁剪
# ----------------------------------------------------------------

@app.get("/api/v1/probes/{probe_id}/preview", tags=["probes"])
def probe_preview(probe_id: int,
                  session: Session = Depends(get_session), user: dict = Depends(current_user)):
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "probe 不存在")
    _require_project_access(probe.project_id, session, user)
    storage = get_storage()
    data = storage.get_object(probe.object_uri)
    if data is None:
        raise HTTPException(404, "图片文件不存在")
    ext = Path(probe.object_uri).suffix.lstrip(".") or "jpg"
    mime = "image/png" if ext == "png" else "image/jpeg"
    return StreamingResponse(BytesIO(data), media_type=mime)


@app.get("/api/v1/probes/{probe_id}/diagnostics", tags=["probes"])
def probe_diagnostics(probe_id: int,
                      session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """返回每张人脸的最近候选，即使相似度低于业务阈值也用于解释漏匹配原因。"""
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "probe 不存在")
    _require_project_access(probe.project_id, session, user)
    gallery = build_gallery_from_db(session, probe.project_id)
    out = []
    for det in probe.detections:
        emb = session.scalar(select(Embedding).filter(
            Embedding.owner_type == "probe", Embedding.owner_id == det.id
        ))
        if emb is None or not det.usable:
            out.append({"probe_face_id": det.id, "best_candidates": [], "usable": False,
                        "quality_score": det.quality_score, "reason": "人脸质量不足或未生成特征"})
            continue
        candidates = gallery.search(np.asarray(emb.vector, dtype=np.float32), include_below_threshold=True)
        out.append({
            "probe_face_id": det.id,
            "usable": True,
            "quality_score": det.quality_score,
            "best_candidates": [
                {"subject_code": c.external_code, "subject_id": c.subject_id,
                 "similarity": c.similarity, "decision_band": c.decision_band}
                for c in candidates[:3]
            ],
            "reason": "已超过最低阈值" if candidates and candidates[0].decision_band != "rejected" else "最近候选未达到最低阈值",
            "threshold_low": gallery.th_low,
        })
    return {"probe_id": probe_id, "model_version": get_settings().default_model_version, "faces": out}


@app.get("/api/v1/probes/{probe_id}/faces/{face_id}/crop", tags=["probes"])
def face_crop(probe_id: int, face_id: int,
              session: Session = Depends(get_session), user: dict = Depends(current_user)):
    """返回指定人脸区域的裁剪图"""
    det = session.get(FaceDetection, face_id)
    if det is None or det.probe_image_id != probe_id:
        raise HTTPException(404, "人脸检测不存在")
    probe = session.get(ProbeImage, probe_id)
    if probe is None:
        raise HTTPException(404, "probe 不存在")
    _require_project_access(probe.project_id, session, user)
    storage = get_storage()
    data = storage.get_object(probe.object_uri)
    if data is None:
        raise HTTPException(404, "图片文件不存在")
    # 裁剪
    import numpy as np
    from PIL import Image
    img = Image.open(BytesIO(data)).convert("RGB")
    bbox = det.bbox or {}
    x = int(bbox.get("x", 0))
    y = int(bbox.get("y", 0))
    w = int(bbox.get("w", 0))
    h = int(bbox.get("h", 0))
    if w <= 0 or h <= 0:
        # 默认中心裁剪
        w, h = img.width // 2, img.height // 2
        x = (img.width - w) // 2
        y = (img.height - h) // 2
    face = img.crop((x, y, x + w, y + h))
    buf = BytesIO()
    face.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


# ----------------------------------------------------------------
# 评测历史查询
# ----------------------------------------------------------------
@app.get("/api/v1/evaluation/runs", tags=["evaluation"])
def list_eval_runs(session: Session = Depends(get_session)):
    runs = session.scalars(
        select(EvaluationRun).order_by(EvaluationRun.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "name": r.dataset_name or f"评测 #{r.id}",
            "dataset_name": r.dataset_name,
            "model_version": r.model_version,
            "status": r.status or ("success" if r.metrics_json else "running"),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "metrics_json": r.metrics_json,
            "summary": r.summary,
        }
        for r in runs
    ]


@app.on_event("startup")
def on_start():
    # 本地演示自动创建管理员；正式部署请通过 FACE_ADMIN_PASSWORD 覆盖默认密码。
    with session_scope() as session:
        # SQLite fallback needs a one-time additive migration for archive support.
        try:
            cols = {row[1] for row in session.execute(text("PRAGMA table_info(probe_images)"))}
            if cols and "archived_at" not in cols:
                session.execute(text("ALTER TABLE probe_images ADD COLUMN archived_at DATETIME"))
                session.commit()
        except Exception:
            # PostgreSQL deployments use an explicit migration tool; do not run SQLite SQL there.
            session.rollback()
        if session.scalar(select(User).limit(1)) is None:
            admin_password = os.getenv("FACE_ADMIN_PASSWORD", "admin123")
            admin = User(username="admin", password_hash=_password_hash(admin_password), role="admin")
            session.add(admin)
            session.flush()
            for project in session.scalars(select(Project)).all():
                session.add(ProjectAccess(user_id=admin.id, project_id=project.id, role="admin"))
    print(f"🚀 {settings.project_name} listening on {settings.api_host}:{settings.api_port}")
    print(f"   DB  : {settings.database_url.split('@')[-1]}")
    print(f"   Model: {settings.default_model_version}")
