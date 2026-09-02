"""严格的公开数据集一对一验证基线。

与旧的 week1_algorithm_validation.py 不同，本脚本：
* 只扫描原始 DrivFace 命名，不读取 stand-in 图片；
* 按人员和文件变体划分 reference/probe，避免同一图片重复使用；
* 只报告一对一验证指标，不把四人小样本包装成生产级 1:N 准确率。

用法：python scripts/public_benchmark.py --limit-per-id 30
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.algorithm.face_engine import FaceEngine, cosine_similarity  # noqa: E402


def scan_drivface() -> Dict[str, List[Path]]:
    """只读取 DrivFace/DrivFace/DrivImages 中的原始 606 张图片。"""
    base = ROOT / "data" / "DrivFace" / "DrivFace" / "DrivImages"
    grouped: Dict[str, List[Path]] = defaultdict(list)
    pattern = re.compile(r"_(\d{1,2})_Driv_", re.IGNORECASE)
    for p in sorted(base.glob("*.jpg")) if base.exists() else []:
        match = pattern.search(p.name)
        if match:
            grouped[f"Person_{int(match.group(1)):03d}"].append(p)
    return dict(grouped)


def split_paths(grouped: Dict[str, List[Path]], reference_per_id: int,
                limit_per_id: int) -> Tuple[Dict[str, List[Path]], List[Tuple[Path, str]]]:
    refs: Dict[str, List[Path]] = {}
    probes: List[Tuple[Path, str]] = []
    for label, paths in sorted(grouped.items()):
        # 优先使用 front 变体作为参考，保留 lr/ll 和剩余 front 做 probe。
        front = [p for p in paths if re.search(r"_f\s*\.jpg$", p.name, re.IGNORECASE)]
        other = [p for p in paths if p not in front]
        ordered = front + other
        if limit_per_id > 0:
            ordered = ordered[:limit_per_id]
        if len(ordered) <= reference_per_id:
            continue
        refs[label] = ordered[:reference_per_id]
        probes.extend((p, label) for p in ordered[reference_per_id:])
    return refs, probes


def extract(engine: FaceEngine, paths: Iterable[Path]) -> Dict[Path, np.ndarray]:
    vectors: Dict[Path, np.ndarray] = {}
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        faces = engine.detect_and_extract(image, min_face_size=20, compute_embedding=True)
        usable = [f for f in faces if f.usable and f.embedding is not None]
        if usable:
            # 只保留质量最高的人脸，避免多人图片的身份标签歧义。
            face = max(usable, key=lambda item: item.quality_score)
            vectors[path] = np.asarray(face.embedding, dtype=np.float32)
    return vectors


def build_pairs(refs: Dict[str, List[Path]], probes: List[Tuple[Path, str]],
                vectors: Dict[Path, np.ndarray], max_pairs: int, seed: int = 42):
    rng = np.random.RandomState(seed)
    by_label = defaultdict(list)
    for path, label in probes:
        if path in vectors:
            by_label[label].append(path)
    positive = []
    for label, ref_paths in refs.items():
        for ref in ref_paths:
            if ref not in vectors:
                continue
            for probe in by_label.get(label, []):
                positive.append((label, label, cosine_similarity(vectors[ref], vectors[probe]), 1, ref.name, probe.name))
    negatives = []
    labels = sorted(set(refs) & set(by_label))
    for la in labels:
        for lb in labels:
            if la >= lb:
                continue
            for ref in refs[la]:
                if ref not in vectors:
                    continue
                for probe in by_label[lb]:
                    negatives.append((la, lb, cosine_similarity(vectors[ref], vectors[probe]), 0, ref.name, probe.name))
    rng.shuffle(positive)
    rng.shuffle(negatives)
    half = max_pairs // 2
    return positive[:half] + negatives[:half]


def metrics(rows: List[tuple]) -> Dict[str, object]:
    if not rows:
        return {"note": "没有成功提取到足够的人脸特征"}
    y = np.asarray([r[3] for r in rows], dtype=np.int32)
    score = np.asarray([r[2] for r in rows], dtype=np.float32)
    result: Dict[str, object] = {
        "pairs": int(len(rows)),
        "genuine_pairs": int(y.sum()),
        "impostor_pairs": int((1 - y).sum()),
    }
    try:
        from sklearn.metrics import auc, roc_curve
        fpr, tpr, thresholds = roc_curve(y, score)
        result["auc"] = round(float(auc(fpr, tpr)), 6)
        fnmr = 1 - tpr
        idx = int(np.argmin(np.abs(fpr - fnmr)))
        result["eer"] = round(float((fpr[idx] + fnmr[idx]) / 2), 6)
        result["eer_threshold"] = round(float(thresholds[idx]), 6)
        eligible = np.where(fpr <= 1e-3)[0]
        k = int(eligible[-1]) if len(eligible) else 0
        result["fmr_target"] = 0.001
        result["threshold_at_fmr_0_001"] = round(float(thresholds[k]), 6)
        result["fnmr_at_fmr_0_001"] = round(float(fnmr[k]), 6)
    except Exception as exc:
        result["metric_error"] = str(exc)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-per-id", type=int, default=3)
    parser.add_argument("--limit-per-id", type=int, default=30,
                        help="每个身份最多使用多少张，0 表示全部")
    parser.add_argument("--max-pairs", type=int, default=3000)
    args = parser.parse_args()

    grouped = scan_drivface()
    refs, probes = split_paths(grouped, args.reference_per_id, args.limit_per_id)
    all_paths = [p for paths in refs.values() for p in paths] + [p for p, _ in probes]
    model_root = str(ROOT / "backend" / "models")
    engine = FaceEngine(providers=["CPUExecutionProvider"], model_root=model_root)
    if engine._fallback:
        raise RuntimeError("检测到 fallback 特征，不能生成识别评测结果")
    started = time.time()
    vectors = extract(engine, all_paths)
    rows = build_pairs(refs, probes, vectors, args.max_pairs)

    out = ROOT / "output" / "public_benchmark"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "verification_pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["label_a", "label_b", "similarity", "is_genuine", "reference", "probe"])
        writer.writerows(rows)
    summary = {
        "protocol": "DrivFace strict subject-disjoint reference/probe 1:1 verification",
        "dataset": "DrivFace original DrivImages only",
        "num_subjects": len(refs),
        "images_scanned": len(all_paths),
        "reference_per_subject": args.reference_per_id,
        "probe_images": len(probes),
        "embedded_images": len(vectors),
        "model": "InsightFace buffalo_l (SCRFD + ArcFace R50)",
        "fallback": bool(engine._fallback),
        "elapsed_ms": int((time.time() - started) * 1000),
        "metrics": metrics(rows),
        "limitations": [
            "DrivFace 只有 4 个身份，只能作为车内域小样本压力测试。",
            "该结果不代表大规模人员库或公共场景识别能力。",
            "本脚本不执行一对多名单搜索。",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(
        "公开数据集严格一对一验证\n\n" +
        "协议：" + summary["protocol"] + "\n" +
        "身份数：" + str(summary["num_subjects"]) + "\n" +
        "参考图/人：" + str(summary["reference_per_subject"]) + "\n" +
        "Probe：" + str(summary["probe_images"]) + "\n" +
        "成功提取特征：" + str(summary["embedded_images"]) + "\n" +
        "指标：" + json.dumps(summary["metrics"], ensure_ascii=False) + "\n\n" +
        "限制：" + "；".join(summary["limitations"]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
