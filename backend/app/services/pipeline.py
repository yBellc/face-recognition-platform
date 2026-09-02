"""
核心 Pipeline 服务：
  接收 probe_image_id -> 下载图片 -> 检测 -> 特征 -> 向量检索 -> 候选入库 -> 生成复核任务

对应方案第六部分：1/2/3/4/5 号服务（图片接收/人脸检测/特征提取/候选检索/人工复核）
在第2周阶段我们把所有服务合并在一个同步函数里，
后续再按需要拆成独立的 Celery worker 微服务。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.face_engine import (
    FaceEngine, ReferenceGallery, DetectedFace, Candidate,
    decision_band_of, sha256_of_file,
)
from app.config import get_settings
from app.db.models import (
    Embedding, FaceDetection, MatchCandidate, ProbeImage, ReferenceImage,
    ReviewTask, Subject, Project, AuditLog, ThresholdProfile,
)
from app.services.storage import get_storage


# ---- 全局单例 -------------------------------------------------------------
_face_engine: Optional[FaceEngine] = None


def get_face_engine() -> FaceEngine:
    global _face_engine
    if _face_engine is None:
        s = get_settings()
        model_root = s.insightface_model_root or str(
            Path(__file__).resolve().parent.parent.parent / "models"
        )
        _face_engine = FaceEngine(
            providers=s.insightface_providers,
            model_root=model_root,
        )
    return _face_engine


# ---- 工具 -----------------------------------------------------------------
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _log_audit(session: Session, actor: str, action: str, resource: str,
               metadata: Optional[Dict] = None):
    session.add(AuditLog(actor=actor, action=action, resource=resource,
                         meta_json=metadata))


# ---- 参考库构建：每次处理都从 DB 构建（小规模项目可接受） ---------------
def build_gallery_from_db(session: Session, project_id: int) -> ReferenceGallery:
    s = get_settings()
    profile = session.scalar(select(ThresholdProfile).filter(ThresholdProfile.project_id == project_id))
    threshold_high = profile.high if profile else s.threshold_high
    threshold_medium = profile.medium if profile else s.threshold_medium
    threshold_low = profile.low if profile else s.threshold_low
    gallery = ReferenceGallery(
        threshold_high=threshold_high,
        threshold_medium=threshold_medium,
        threshold_low=threshold_low,
        top_k=s.top_k_candidates,
    )
    # 取 project_id 下所有 reference embedding (owner_type='reference')
    # 通过 owner_id = face_detection.id WHERE reference_image_id IS NOT NULL
    rows = (
        session.query(
            Subject.external_code,
            Subject.id.label("subject_id"),
            Embedding.vector,
        )
        .select_from(Embedding)
        .join(FaceDetection, FaceDetection.id == Embedding.owner_id)
        .join(ReferenceImage, ReferenceImage.id == FaceDetection.reference_image_id)
        .join(Subject, Subject.id == ReferenceImage.subject_id)
        .filter(
            Embedding.owner_type == "reference",
            Subject.project_id == project_id,
        )
        .all()
    )
    for code, sid, vec in rows:
        gallery.add_subject(code, subject_id=sid)
        if vec is not None:
            gallery.add_reference(code, np.asarray(vec, dtype=np.float32))
    return gallery


# ---- 把参考图注册进 DB（人员库构建） -------------------------------------
def register_reference_image(
    session: Session,
    project_id: int,
    external_code: str,
    image_bytes: bytes,
    file_ext: str = "jpg",
    source_type: str = "authorized_upload",
) -> Optional[Dict]:
    """
    1. 确保项目和 subject 存在
    2. 存对象存储
    3. 跑人脸检测，取第一个可用人脸：入库 (reference_images + face_detections + embeddings)
    """
    s = get_settings()
    storage = get_storage()
    engine = get_face_engine()

    project = session.get(Project, project_id)
    if project is None:
        return None

    subj = (
        session.query(Subject)
        .filter(Subject.project_id == project_id,
                Subject.external_code == external_code)
        .first()
    )
    if subj is None:
        subj = Subject(project_id=project_id, external_code=external_code)
        session.add(subj); session.flush()

    # 解码 + 检测
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"error": "无法解码图片", "subject_id": subj.id}

    faces = engine.detect_and_extract(img, min_face_size=s.min_face_size,
                                       compute_embedding=True)
    usable = [f for f in faces if f.usable and f.embedding is not None]
    if not usable:
        return {"error": "未检测到可用人脸", "subject_id": subj.id,
                "detected": len(faces)}

    # 参考库必须保证一张照片对应一个人，避免把多人照片中随意挑出的
    # 驾驶员或路人误注册到当前重点对象下。
    if len(usable) > 1:
        return {
            "error": f"参考照片中检测到 {len(usable)} 张可用人脸，请上传只包含一个人的照片",
            "subject_id": subj.id,
            "detected": len(faces),
        }

    digest = sha256_bytes(image_bytes)
    key = f"{external_code}/{digest[:8]}_{int(time.time()*1000)}.{file_ext.lstrip('.')}"
    uri = storage.put_object(
        s.minio_bucket_reference, key, image_bytes,
        content_type=f"image/{file_ext.lstrip('.')}",
    )

    # 只选质量最高的一张作为参考特征
    face = max(usable, key=lambda f: f.quality_score)

    ref = ReferenceImage(
        subject_id=subj.id, object_uri=uri, source_type=source_type,
        quality_score=face.quality_score, sha256=digest,
    )
    session.add(ref); session.flush()

    det = FaceDetection(
        reference_image_id=ref.id, owner_type="reference",
        bbox={"x": face.bbox.x, "y": face.bbox.y, "w": face.bbox.w, "h": face.bbox.h},
        landmarks=face.landmarks.tolist() if face.landmarks is not None else None,
        detector_score=face.detector_score, quality_score=face.quality_score,
        blur_score=face.blur_score, pose=face.pose,
        occlusion_score=face.occlusion_score, usable=True,
    )
    session.add(det); session.flush()

    emb = Embedding(
        owner_type="reference", owner_id=det.id,
        model_version=s.default_model_version,
        vector=face.embedding.astype(np.float32).tolist(),
        norm=float(np.linalg.norm(face.embedding)),
    )
    session.add(emb)

    _log_audit(session, actor="system", action="register_reference",
               resource=f"subject/{subj.id}",
               metadata={"code": external_code, "image_uri": uri})
    session.flush()
    return {
        "subject_id": subj.id,
        "reference_image_id": ref.id,
        "detection_id": det.id,
        "embedding_id": emb.id,
        "quality_score": face.quality_score,
        "object_uri": uri,
    }


# ---- 完整处理：probe 图片 -> 候选 ----------------------------------------
def process_probe(session: Session, probe_id: int) -> Dict:
    s = get_settings()
    storage = get_storage()
    engine = get_face_engine()

    probe: Optional[ProbeImage] = session.get(ProbeImage, probe_id)
    if probe is None:
        return {"error": f"probe {probe_id} 不存在"}

    # Celery 重试/网络重复投递时，已完成的任务直接返回，避免重复写入检测和候选。
    if probe.processing_status == "processed":
        face_count = len(probe.detections)
        return {"probe_id": probe_id, "status": "processed", "num_faces": face_count,
                "processing_ms": probe.processing_ms}

    # 重新处理前清理旧结果，保证“重试”不会叠加出重复人脸和重复候选。
    old_det_ids = [d.id for d in session.scalars(
        select(FaceDetection).filter(FaceDetection.probe_image_id == probe_id)
    ).all()]
    if old_det_ids:
        old_candidate_ids = [c.id for c in session.scalars(
            select(MatchCandidate).filter(MatchCandidate.probe_face_id.in_(old_det_ids))
        ).all()]
        if old_candidate_ids:
            session.query(ReviewTask).filter(ReviewTask.candidate_id.in_(old_candidate_ids)).delete(synchronize_session=False)
            session.query(MatchCandidate).filter(MatchCandidate.id.in_(old_candidate_ids)).delete(synchronize_session=False)
        session.query(Embedding).filter(
            Embedding.owner_type == "probe", Embedding.owner_id.in_(old_det_ids)
        ).delete(synchronize_session=False)
        session.query(FaceDetection).filter(FaceDetection.id.in_(old_det_ids)).delete(synchronize_session=False)
        session.flush()

    t0 = time.time()
    probe.processing_status = "processing"
    probe.error_message = None
    session.flush()
    try:
        # 1. 下载到本地
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        local_path: Optional[str] = None
        if probe.object_uri.startswith("s3://") or probe.object_uri.startswith("file://"):
            # 解析 bucket / key
            if probe.object_uri.startswith("s3://"):
                rest = probe.object_uri[len("s3://"):]
                bucket, key = rest.split("/", 1)
            else:
                # fallback
                bucket = s.minio_bucket_probe
                key = Path(probe.object_uri[len("file://"):]).name
                # 直接用本地文件
                actual = Path(probe.object_uri[len("file://"):])
                if actual.exists():
                    local_path = str(actual)
            if local_path is None:
                local_path = storage.get_local_path_or_download(bucket, key, tmp_path)
        elif os.path.exists(probe.object_uri):
            local_path = probe.object_uri
        if not local_path or not os.path.exists(local_path):
            raise FileNotFoundError(f"图片不可访问: {probe.object_uri}")

        # 2. 读取 + 检测/特征
        img = cv2.imread(local_path, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cv2 读取失败: {local_path}")
        faces = engine.detect_and_extract(img, min_face_size=s.min_face_size,
                                           compute_embedding=True)

        # 3. 把检测和特征写入 DB
        face_ids: List[int] = []
        for face in faces:
            det = FaceDetection(
                probe_image_id=probe.id, owner_type="probe",
                bbox={"x": face.bbox.x, "y": face.bbox.y,
                      "w": face.bbox.w, "h": face.bbox.h,
                      "score": float(face.bbox.score)},
                landmarks=face.landmarks.tolist() if face.landmarks is not None else None,
                detector_score=face.detector_score,
                quality_score=face.quality_score, blur_score=face.blur_score,
                pose=face.pose, occlusion_score=face.occlusion_score,
                usable=bool(face.usable),
            )
            session.add(det); session.flush()
            face_ids.append(det.id)

            if face.usable and face.embedding is not None:
                session.add(Embedding(
                    owner_type="probe", owner_id=det.id,
                    model_version=s.default_model_version,
                    vector=face.embedding.astype(np.float32).tolist(),
                    norm=float(np.linalg.norm(face.embedding)),
                ))

        # 4. 构建 gallery 并做 1:N 检索，生成候选 + 复核任务
        gallery = build_gallery_from_db(session, project_id=probe.project_id)
        if gallery.num_embeddings() == 0:
            # 空库：不生成候选
            pass
        else:
            for face, det_id in zip(faces, face_ids):
                if not face.usable or face.embedding is None:
                    continue
                cands: List[Candidate] = gallery.search(face.embedding)
                for c in cands:
                    # 根据 subject_id 反查（gallery 中存过）
                    mc = MatchCandidate(
                        probe_face_id=det_id, subject_id=c.subject_id or 0,
                        similarity=c.similarity, rank=c.rank,
                        decision_band=c.decision_band, status="pending",
                    )
                    session.add(mc); session.flush()
                    # 自动建立复核任务（待人工处理）
                    session.add(ReviewTask(candidate_id=mc.id))

        probe.processing_status = "processed"
        probe.processing_ms = int((time.time() - t0) * 1000)

    except Exception as e:
        probe.processing_status = "failed"
        probe.error_message = str(e)
        session.flush()
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return {"probe_id": probe_id, "status": "failed", "error": str(e)}

    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    _log_audit(session, actor="system", action="process_probe",
               resource=f"probe/{probe_id}",
               metadata={
                   "num_faces": len(faces),
                   "processing_ms": probe.processing_ms,
               })
    session.flush()

    return {
        "probe_id": probe_id,
        "status": probe.processing_status,
        "num_faces": len(faces),
        "processing_ms": probe.processing_ms,
    }


# ---- 重新生成特征 ---------------------------------------------------------
def re_embed_subject(session: Session, subject_id: int):
    """重新处理指定 subject 下所有参考图的特征"""
    s = get_settings()
    engine = get_face_engine()
    storage = get_storage()

    subj = session.get(Subject, subject_id)
    if subj is None:
        raise ValueError(f"subject {subject_id} 不存在")

    # 取该 subject 下所有参考图
    refs = session.query(ReferenceImage).filter(
        ReferenceImage.subject_id == subject_id
    ).all()

    for ref in refs:
        data = storage.get_object(ref.object_uri)
        if data is None:
            continue
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        faces = engine.detect_and_extract(img, min_face_size=s.min_face_size,
                                           compute_embedding=True)
        usable = [f for f in faces if f.usable and f.embedding is not None]
        if not usable:
            continue
        face = max(usable, key=lambda f: f.quality_score)

        # 删除旧的 detection + embedding
        old_dets = session.query(FaceDetection).filter(
            FaceDetection.reference_image_id == ref.id
        ).all()
        for od in old_dets:
            session.query(Embedding).filter(
                Embedding.owner_type == "reference",
                Embedding.owner_id == od.id,
            ).delete(synchronize_session=False)
            session.delete(od)

        # 新建
        det = FaceDetection(
            reference_image_id=ref.id, owner_type="reference",
            bbox={"x": face.bbox.x, "y": face.bbox.y,
                  "w": face.bbox.w, "h": face.bbox.h},
            landmarks=face.landmarks.tolist() if face.landmarks is not None else None,
            detector_score=face.detector_score, quality_score=face.quality_score,
            blur_score=face.blur_score, pose=face.pose,
            occlusion_score=face.occlusion_score, usable=True,
        )
        session.add(det); session.flush()
        emb = Embedding(
            owner_type="reference", owner_id=det.id,
            model_version=s.default_model_version,
            vector=face.embedding.astype(np.float32).tolist(),
            norm=float(np.linalg.norm(face.embedding)),
        )
        session.add(emb)
        ref.quality_score = face.quality_score

    session.flush()
