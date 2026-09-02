"""
算法核心模块：人脸检测 + 关键点对齐 + 质量评估 + 特征提取 + 相似度检索

单文件纯 Python 实现，不依赖数据库即可单独运行（第1周交付物）。
依赖：insightface, opencv-python, numpy
"""
from __future__ import annotations

import os
import time
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np


# ======================================================================
# 数据结构
# ======================================================================
@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int
    score: float = 0.0

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)


@dataclass
class DetectedFace:
    bbox: BBox
    landmarks: np.ndarray  # shape (5, 2) - 左眼/右眼/鼻尖/左嘴角/右嘴角
    detector_score: float = 0.0
    quality_score: float = 0.0   # 综合质量
    blur_score: float = 0.0      # 越低越模糊 (Laplacian 方差)
    pose: Dict[str, float] = field(default_factory=dict)  # yaw/pitch/roll
    occlusion_score: float = 0.0
    usable: bool = True
    aligned_face: Optional[np.ndarray] = None  # 对齐后人脸图 (112,112,3)
    embedding: Optional[np.ndarray] = None     # 512维向量


@dataclass
class Candidate:
    external_code: str       # Person_017
    subject_id: Optional[int]
    similarity: float        # 余弦相似度 0-1
    rank: int = 0
    decision_band: str = "low"  # high/medium/low


@dataclass
class ProcessingResult:
    image_path: str
    image_sha256: str
    num_faces: int
    detections: List[DetectedFace] = field(default_factory=list)
    candidates_by_face: List[List[Candidate]] = field(default_factory=list)
    processing_ms: int = 0
    error: Optional[str] = None


# ======================================================================
# 工具函数
# ======================================================================
def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """a, b 应为 L2 归一化后的向量"""
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v)
    if norm < 1e-12:
        return v
    return v / norm


def decision_band_of(sim: float, high: float, medium: float, low: float) -> str:
    if sim >= high:
        return "high"
    if sim >= medium:
        return "medium"
    if sim >= low:
        return "low"
    return "rejected"


# ======================================================================
# 1. 五点关键点对齐 (标准 ArcFace 目标坐标)
# ======================================================================
# 112x112 标准目标坐标 (MS1M 风格)
_STANDARD_LANDMARKS = np.array(
    [
        [38.2946, 51.6963],  # 左眼
        [73.5318, 51.5014],  # 右眼
        [56.0252, 71.7366],  # 鼻尖
        [41.5493, 92.3655],  # 左嘴角
        [70.7299, 92.2041],  # 右嘴角
    ],
    dtype=np.float32,
)


def align_face(image: np.ndarray, landmarks: np.ndarray,
               out_size: Tuple[int, int] = (112, 112)) -> np.ndarray:
    """
    基于 5 点关键点做相似变换对齐
    image: BGR (opencv)
    landmarks: (5,2)
    """
    if landmarks is None or landmarks.shape[0] != 5:
        # fallback: 简单 resize
        return cv2.resize(image, out_size)
    src = landmarks.astype(np.float32)
    dst = _STANDARD_LANDMARKS.astype(np.float32)
    M, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if M is None:
        return cv2.resize(image, out_size)
    return cv2.warpAffine(image, M, out_size,
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


# ======================================================================
# 2. 质量评估 (方案第六部分第2条：尺寸/模糊/光照/姿态/遮挡/反光)
# ======================================================================
def estimate_face_quality(face_img: np.ndarray,
                          bbox: BBox,
                          landmarks: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """
    返回:
      blur_score:   Laplacian方差, 越大越清晰
      brightness:   平均亮度 0-255
      pose:         {yaw, pitch, roll} (度, 粗略估计)
      size_ok:      是否满足最小尺寸
      occlusion_score: 估算遮挡 (0=无, 1=完全遮挡)
      overall:      综合 0-1
    """
    h, w = face_img.shape[:2]
    gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if face_img.ndim == 3 else face_img

    # 模糊度 (Laplacian 方差)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_norm = min(1.0, blur / 300.0)

    # 亮度
    brightness = float(gray.mean())
    bright_norm = 1.0 - abs(brightness - 127.5) / 127.5

    # 尺寸
    size_ok = (bbox.w >= 40 and bbox.h >= 40)
    size_norm = min(1.0, min(bbox.w, bbox.h) / 120.0)

    # 姿态 (用 5 点粗略估：yaw = 左右眼x差 vs 嘴中心偏左)
    yaw, pitch, roll = 0.0, 0.0, 0.0
    if landmarks is not None and len(landmarks) == 5:
        le, re, nose, lm, rm = landmarks
        eye_dx = re[0] - le[0]
        eye_dy = re[1] - le[1]
        roll = float(np.degrees(np.arctan2(eye_dy, max(1e-6, eye_dx))))
        mouth_cx = (lm[0] + rm[0]) / 2.0
        face_cx = (le[0] + re[0]) / 2.0
        # yaw 近似：鼻子相对眼中心的水平偏移 / 眼间距
        eye_dist = max(1e-6, np.linalg.norm(re - le))
        yaw = float(np.degrees(np.arctan((nose[0] - face_cx) / eye_dist))) * 2.0
        # pitch 近似：鼻到眼中心 vs 鼻到嘴中心 的竖直比例
        eye_center_y = (le[1] + re[1]) / 2.0
        mouth_center_y = (lm[1] + rm[1]) / 2.0
        v1 = nose[1] - eye_center_y
        v2 = mouth_center_y - nose[1]
        if v2 > 1:
            ratio = v1 / v2
            # 正常约 1.0，大于 1 = 低头（pitch>0），小于 1 = 抬头
            pitch = float(np.degrees(np.arctan((ratio - 1.0)))) * 50.0

    pose_ok = (abs(yaw) < 45) and (abs(pitch) < 30) and (abs(roll) < 20)
    pose_norm = 1.0 - min(1.0, (abs(yaw) + abs(pitch) + abs(roll)) / 120.0)

    # 遮挡：简单版 - 若人脸边缘处亮度突变多则可能有遮挡
    edge_mask = cv2.Canny(gray, 100, 200)
    border_ratio = float(edge_mask[: int(h * 0.1), :].mean() + edge_mask[-int(h * 0.1):, :].mean()) / (255.0 + 1e-6)
    occlusion = min(1.0, border_ratio * 3.0)
    occlu_norm = 1.0 - occlusion

    # 综合分（加权）
    weights = {"blur": 0.40, "bright": 0.15, "size": 0.20, "pose": 0.20, "occlu": 0.05}
    overall = (
        weights["blur"] * blur_norm
        + weights["bright"] * bright_norm
        + weights["size"] * size_norm
        + weights["pose"] * pose_norm
        + weights["occlu"] * occlu_norm
    )

    return {
        "blur_score": blur,
        "brightness": brightness,
        "pose": {"yaw": round(yaw, 2), "pitch": round(pitch, 2), "roll": round(roll, 2)},
        "pose_ok": pose_ok,
        "size_ok": size_ok,
        "occlusion_score": round(occlusion, 3),
        "overall": round(float(overall), 4),
    }


# ======================================================================
# 3. InsightFace 引擎封装
# ======================================================================
class FaceEngine:
    """
    统一封装：检测+关键点+对齐+特征提取
    优先使用 insightface 官方包；若未安装则提供 fallback (OpenCV DNN + 假特征)
    以便在未安装依赖时也能跑通端到端流程。
    """

    def __init__(self, providers: Optional[List[str]] = None, name: str = "buffalo_l",
                 model_root: Optional[str] = None):
        self.providers = providers or ["CPUExecutionProvider"]
        self.model_name = name
        self.model_root = model_root  # 自定义模型目录
        self._analysis = None      # insightface FaceAnalysis
        self._fallback = False     # 是否使用 fallback
        self._init_engine()

    # ---- 初始化 ---------------------------------------------------------
    def _init_engine(self):
        try:
            from insightface.app import FaceAnalysis
            # 如果用户提供了本地模型路径，先检查文件是否存在
            if self.model_root:
                expected = Path(self.model_root) / "models" / self.model_name
                if not expected.exists():
                    raise FileNotFoundError(f"模型目录不存在: {expected}. 请先下载 buffalo_l.zip 并解压到此位置")
            self._analysis = FaceAnalysis(
                name=self.model_name,
                providers=self.providers,
                root=self.model_root,  # 覆盖默认 ~/.insightface
            )
            # 不设 det_size 默认会用 640x640，能兼容小图
            self._analysis.prepare(ctx_id=0 if "CUDA" in self.providers[0] else -1,
                                   det_size=(640, 640))
            print(f"[FaceEngine] 加载 InsightFace {self.model_name} 成功 (模型路径: {self.model_root or '~/.insightface'})")
        except Exception as e:
            print(f"[FaceEngine] InsightFace 未加载，使用 fallback 模式: {e}")
            self._fallback = True
            # 尝试加载 OpenCV DNN 的人脸检测器作为最低保障
            self._cv_detector = self._load_opencv_detector()

    def _load_opencv_detector(self):
        try:
            model_file = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            return cv2.CascadeClassifier(model_file)
        except Exception:
            return None

    # ---- 对外接口 -------------------------------------------------------
    def detect_and_extract(self, image_bgr: np.ndarray,
                           min_face_size: int = 40,
                           compute_embedding: bool = True) -> List[DetectedFace]:
        """检测 + 对齐 + 质量评估 + (可选)特征提取"""
        results: List[DetectedFace] = []
        h, w = image_bgr.shape[:2]

        if self._fallback:
            faces = self._detect_fallback(image_bgr, min_face_size)
        else:
            faces = self._detect_insightface(image_bgr, min_face_size)

        for (bbox, kps) in faces:
            # 裁剪人脸 + 对齐
            x, y, fw, fh = bbox.as_tuple()
            pad = int(0.3 * max(fw, fh))
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + fw + pad)
            y2 = min(h, y + fh + pad)
            crop = image_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            # 将关键点平移到裁剪坐标系
            kps_local = kps.copy() - np.array([x1, y1], dtype=np.float32) if kps is not None else None
            aligned = align_face(crop, kps_local)

            # 质量评估（用对齐后人脸做统一判断）
            q = estimate_face_quality(aligned, bbox, kps)
            # InsightFace 路径: detector_score 已可靠，放宽 pose 要求
            if not self._fallback and bbox.score >= 0.5:
                usable = bool(q["size_ok"] and q["overall"] >= 0.35)
            else:
                usable = bool(q["size_ok"] and q["pose_ok"] and q["overall"] >= 0.35)

            face = DetectedFace(
                bbox=bbox,
                landmarks=kps if kps is not None else np.zeros((5, 2), dtype=np.float32),
                detector_score=bbox.score,
                quality_score=float(q["overall"]),
                blur_score=float(q["blur_score"]),
                pose=q["pose"],
                occlusion_score=float(q["occlusion_score"]),
                usable=usable,
                aligned_face=aligned,
            )

            if compute_embedding and usable:
                face.embedding = self._extract_embedding(aligned, crop, kps_local)

            results.append(face)
        return results

    # ---- 内部：检测 ----------------------------------------------------
    def _detect_insightface(self, img, min_face_size):
        out = []
        try:
            faces = self._analysis.get(img)
            for f in faces:
                x1, y1, x2, y2 = [int(v) for v in f.bbox]
                bw, bh = x2 - x1, y2 - y1
                if bw < min_face_size or bh < min_face_size:
                    continue
                score = float(getattr(f, "det_score", 0.0))
                bbox = BBox(x1, y1, bw, bh, score)
                kps = None
                if hasattr(f, "kps") and f.kps is not None:
                    kps = np.asarray(f.kps, dtype=np.float32).reshape(-1, 2)
                    if kps.shape[0] >= 5:
                        kps = kps[:5]
                out.append((bbox, kps))
        except Exception as e:
            print(f"[FaceEngine] InsightFace 检测失败: {e}")
        return out

    def _detect_fallback(self, img, min_face_size):
        out = []
        if self._cv_detector is None:
            return out
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        rects = self._cv_detector.detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=5,
            minSize=(min_face_size, min_face_size),
        )
        for (x, y, w, h) in rects:
            bbox = BBox(int(x), int(y), int(w), int(h), 0.9)
            # fallback 关键点：近似估计5点
            cx, cy = x + w / 2, y + h / 2
            eye_y = y + h * 0.38
            mouth_y = y + h * 0.78
            kps = np.array([
                [cx - w * 0.22, eye_y],
                [cx + w * 0.22, eye_y],
                [cx, y + h * 0.55],
                [cx - w * 0.18, mouth_y],
                [cx + w * 0.18, mouth_y],
            ], dtype=np.float32)
            out.append((bbox, kps))
        return out

    # ---- 内部：特征提取 -------------------------------------------------
    def _extract_embedding(self, aligned_img: np.ndarray,
                           original_crop: np.ndarray = None,
                           kps: np.ndarray = None) -> np.ndarray:
        if not self._fallback:
            try:
                # insightface 的 recognizer 接受对齐好的 112x112 图
                # FaceAnalysis 的 get() 已带 embedding，但这里为了可控单独计算
                model = getattr(self._analysis, "models", {}).get("recognition", None)
                if model is None:
                    # 直接用 analysis 对单脸图重算
                    res = self._analysis.get(aligned_img)
                    if len(res) > 0 and hasattr(res[0], "embedding"):
                        emb = np.asarray(res[0].embedding, dtype=np.float32)
                        return l2_normalize(emb)
                else:
                    import insightface
                    net_out = model.get_feat([aligned_img[:, :, ::-1]])
                    if isinstance(net_out, list):
                        net_out = net_out[0]
                    return l2_normalize(np.asarray(net_out, dtype=np.float32).flatten())
            except Exception as e:
                print(f"[FaceEngine] InsightFace 特征失败: {e}")

        # ---- fallback: 使用颜色直方图+伪随机（仅保证接口通，不具备识别能力）
        return self._fallback_embedding(aligned_img)

    def _fallback_embedding(self, img: np.ndarray, dim: int = 512) -> np.ndarray:
        small = cv2.resize(img, (32, 32))
        hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8],
                            [0, 256, 0, 256, 0, 256]).flatten()
        # 扩展到 512：复制 + 用均值填充
        emb = np.zeros(dim, dtype=np.float32)
        hist = hist.astype(np.float32)
        hlen = min(dim, len(hist))
        emb[:hlen] = hist[:hlen]
        if hlen < dim:
            emb[hlen:] = hist.mean()
        return l2_normalize(emb)


# ======================================================================
# 4. 参考人员库 (内存版 + 向量检索 Top-K)
# ======================================================================
class ReferenceGallery:
    """
    管理参考人员和其参考特征，支持 Top-K 余弦相似度检索
    1:N 检索：对每个 probe 特征与库中所有 reference 特征做余弦相似度，
    取每个 subject 的最高相似度，再排序取 TopK。
    """

    def __init__(self, threshold_high=0.75, threshold_medium=0.60, threshold_low=0.45, top_k=5):
        self.subjects: Dict[str, Dict[str, Any]] = {}   # external_code -> {subject_id, display_name, embeddings: list[array]}
        self.all_vectors: List[np.ndarray] = []
        self.vector_meta: List[Tuple[str, int]] = []    # (external_code, idx in subject.embeddings)
        self.th_high = threshold_high
        self.th_medium = threshold_medium
        self.th_low = threshold_low
        self.top_k = top_k

    # ---- 注册 -----------------------------------------------------------
    def add_subject(self, external_code: str, subject_id: Optional[int] = None,
                    display_name: str = ""):
        if external_code not in self.subjects:
            self.subjects[external_code] = {
                "subject_id": subject_id or len(self.subjects) + 1,
                "display_name": display_name or external_code,
                "embeddings": [],
            }

    def add_reference(self, external_code: str, embedding: np.ndarray):
        self.add_subject(external_code)
        idx = len(self.subjects[external_code]["embeddings"])
        self.subjects[external_code]["embeddings"].append(embedding)
        self.all_vectors.append(embedding)
        self.vector_meta.append((external_code, idx))

    # ---- 检索 -----------------------------------------------------------
    def search(self, probe_embedding: np.ndarray, include_below_threshold: bool = False) -> List[Candidate]:
        if not self.all_vectors or probe_embedding is None:
            return []
        # 批量计算余弦相似度
        mat = np.stack(self.all_vectors, axis=0)  # (N, 512)
        sims = mat @ probe_embedding  # 均已L2归一化，点积即余弦相似度

        # 对每个 subject 取最大相似度
        best_by_subject: Dict[str, Tuple[float, int]] = {}
        for i, sim in enumerate(sims):
            code, _ = self.vector_meta[i]
            cur = best_by_subject.get(code, (-1.0, -1))
            if float(sim) > cur[0]:
                best_by_subject[code] = (float(sim), i)

        ranked = sorted(best_by_subject.items(), key=lambda x: x[1][0], reverse=True)
        cands: List[Candidate] = []
        for r, (code, (sim, _)) in enumerate(ranked[: self.top_k]):
            if sim < self.th_low and not include_below_threshold:
                continue
            cands.append(Candidate(
                external_code=code,
                subject_id=self.subjects[code]["subject_id"],
                similarity=round(sim, 4),
                rank=r + 1,
                decision_band=decision_band_of(sim, self.th_high, self.th_medium, self.th_low),
            ))
        return cands

    # ---- 统计 -----------------------------------------------------------
    def __len__(self):
        return len(self.subjects)

    def num_embeddings(self):
        return len(self.all_vectors)


# ======================================================================
# 5. 完整 pipeline：处理单张图片
# ======================================================================
def process_image(engine: FaceEngine, gallery: ReferenceGallery,
                  image_path: str) -> ProcessingResult:
    t0 = time.time()
    result = ProcessingResult(image_path=image_path, image_sha256="", num_faces=0)
    try:
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"无法读取图片: {image_path}")
        result.image_sha256 = sha256_of_file(image_path)

        detections = engine.detect_and_extract(img, min_face_size=40, compute_embedding=True)
        result.detections = detections
        result.num_faces = len(detections)

        for face in detections:
            if face.usable and face.embedding is not None:
                cands = gallery.search(face.embedding)
            else:
                cands = []
            result.candidates_by_face.append(cands)

        result.processing_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        result.error = str(e)
    return result


# ======================================================================
# 6. 结果可视化（绘制人脸框+候选标签）
# ======================================================================
def draw_result(img_bgr: np.ndarray, result: ProcessingResult) -> np.ndarray:
    out = img_bgr.copy()
    for i, face in enumerate(result.detections):
        x, y, w, h = face.bbox.as_tuple()
        color = (0, 255, 0) if face.usable else (0, 128, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        label = f"#{i + 1} Q{face.quality_score:.2f}"
        cands = result.candidates_by_face[i] if i < len(result.candidates_by_face) else []
        if cands:
            top = cands[0]
            label += f" {top.external_code}@{top.similarity:.2f}[{top.decision_band}]"
        cv2.putText(out, label, (x, max(12, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        # 关键点
        if face.landmarks is not None:
            for (lx, ly) in face.landmarks:
                cv2.circle(out, (int(lx), int(ly)), 2, (0, 255, 255), -1)
    return out
