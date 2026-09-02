"""按 LFW 官方 pairs.txt 协议评测一对一人脸验证。"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.algorithm.face_engine import FaceEngine, cosine_similarity  # noqa: E402


def parse_pairs(path: Path, image_root: Path, limit: int = 0):
    rows = []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) == 3:
            name, a, b = fields
            p1 = image_root / name / f"{name}_{int(a):04d}.jpg"
            p2 = image_root / name / f"{name}_{int(b):04d}.jpg"
            label = 1
        elif len(fields) == 4:
            name1, a, name2, b = fields
            p1 = image_root / name1 / f"{name1}_{int(a):04d}.jpg"
            p2 = image_root / name2 / f"{name2}_{int(b):04d}.jpg"
            label = 0
        else:
            continue
        rows.append((p1, p2, label))
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def extract(engine: FaceEngine, paths):
    vectors = {}
    for path in sorted(set(paths)):
        image = cv2.imread(str(path))
        if image is None:
            continue
        faces = engine.detect_and_extract(image, min_face_size=20, compute_embedding=True)
        usable = [f for f in faces if f.usable and f.embedding is not None]
        if usable:
            face = max(usable, key=lambda item: item.quality_score)
            vectors[path] = np.asarray(face.embedding, dtype=np.float32)
    return vectors


def calculate(rows):
    if not rows:
        return {"pairs": 0, "note": "没有可评测配对"}
    y = np.asarray([r[2] for r in rows], dtype=np.int32)
    scores = np.asarray([r[3] for r in rows], dtype=np.float32)
    result = {"pairs": int(len(rows)), "genuine_pairs": int(y.sum()), "impostor_pairs": int((1-y).sum())}
    from sklearn.metrics import auc, roc_curve
    fpr, tpr, thresholds = roc_curve(y, scores)
    fnmr = 1 - tpr
    eer_i = int(np.argmin(np.abs(fpr - fnmr)))
    result.update({
        "auc": round(float(auc(fpr, tpr)), 6),
        "eer": round(float((fpr[eer_i] + fnmr[eer_i]) / 2), 6),
        "eer_threshold": round(float(thresholds[eer_i]), 6),
    })
    eligible = np.where(fpr <= 1e-3)[0]
    k = int(eligible[-1]) if len(eligible) else 0
    result.update({
        "fmr_target": 0.001,
        "threshold_at_fmr_0_001": round(float(thresholds[k]), 6),
        "fnmr_at_fmr_0_001": round(float(fnmr[k]), 6),
    })
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-pairs", type=int, default=0, help="0 表示评测 pairs.txt 全部 600 对")
    args = parser.parse_args()
    image_root = ROOT / "data" / "LFW" / "lfw"
    pairs_path = ROOT / "data" / "LFW" / "pairs.txt"
    pairs = parse_pairs(pairs_path, image_root, 0)
    if args.limit_pairs > 0 and len(pairs) > args.limit_pairs:
        genuine = [row for row in pairs if row[2] == 1]
        impostor = [row for row in pairs if row[2] == 0]
        half = args.limit_pairs // 2
        pairs = genuine[:half] + impostor[: args.limit_pairs - half]
    engine = FaceEngine(providers=["CPUExecutionProvider"], model_root=str(ROOT / "backend" / "models"))
    if engine._fallback:
        raise RuntimeError("检测到 fallback 特征，拒绝生成 LFW 识别评测结果")
    started = time.time()
    vectors = extract(engine, [p for a, b, _ in pairs for p in (a, b)])
    scored = [(a, b, label, cosine_similarity(vectors[a], vectors[b]))
              for a, b, label in pairs if a in vectors and b in vectors]
    out = ROOT / "output" / "public_benchmark"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "lfw_pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_a", "image_b", "is_genuine", "similarity"])
        writer.writerows((str(a.relative_to(ROOT)), str(b.relative_to(ROOT)), label, score)
                         for a, b, label, score in scored)
    summary = {
        "protocol": "LFW official pairs.txt one-to-one verification",
        "dataset": "LFW",
        "pairs_requested": len(pairs),
        "pairs_scored": len(scored),
        "images_embedded": len(vectors),
        "model": "InsightFace buffalo_l (SCRFD + ArcFace R50)",
        "fallback": bool(engine._fallback),
        "elapsed_ms": int((time.time() - started) * 1000),
        "metrics": calculate(scored),
        "limitations": [
            "LFW 是通用网络照片验证基线，不等同于车内监控域表现。",
            "本评测是 1:1 验证，不代表大规模 1:N 名单检索准确率。",
        ],
    }
    (out / "lfw_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
