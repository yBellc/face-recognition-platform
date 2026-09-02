"""
第1周交付物 —— 数据集 + 算法验证

对应方案里程碑：
  第1周：DrivFace/WIDER FACE 导入 + InsightFace 检测与特征提取 + 基础 1:1 比对 + 第一版离线评测报告

产出：
  output/week1/
    summary.txt           —— 文本版评测报告
    detection_stats.csv   —— 每张图检测结果
    matching_1to1.csv     —— 1:1 相似度矩阵 (正/负样本)
    matching_1toN.csv     —— 1:N 候选检索结果
    roc_curve.png         —— ROC 曲线 (AUC/EER)
    det_curve.png         —— DET 曲线 (FMR vs FNMR)
    samples/*.jpg         —— 可视化样例 (检测框+候选标签)
    gallery.json          —— 参考人员库摘要

用法：
  python scripts/week1_algorithm_validation.py [--full]
  默认快速模式：只处理每个数据集前 N 张，快速出报告；加 --full 跑完整数据
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple, Dict, Any

import cv2
import numpy as np

# 确保能导入 backend.app.algorithm
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.algorithm.face_engine import (
    FaceEngine,
    ReferenceGallery,
    process_image,
    draw_result,
    sha256_of_file,
    cosine_similarity,
    decision_band_of,
)

DATA = ROOT / "data"
OUT = ROOT / "output" / "week1"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = OUT / "samples"
SAMPLES.mkdir(exist_ok=True)


# ======================================================================
# 工具：扫描真实数据集目录
# ======================================================================
def scan_drivface(limit: int) -> List[Tuple[Path, str]]:
    """
    DrivFace 官方文件名格式： 20130529_01_Driv_001_f .jpg
                              ^^ 日期 ^^ subject (01..04)
    同时兼容 stand-in 生成的 Person_00X 命名。
    """
    base = DATA / "DrivFace"
    out: List[Tuple[Path, str]] = []
    if not base.exists():
        return out
    import re
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.ppm", "*.JPG"]:
        for p in base.rglob(ext):
            name = p.name
            # 官方格式：日期_XX_Driv_编号_姿势.jpg，取 subject 号
            m = re.search(r"_([01234]{1,2})_Driv_", name)
            if m:
                label = f"Person_{int(m.group(1)):03d}"
            else:
                m2 = re.search(r"Subject[_\-]?(\d+)", name, re.IGNORECASE)
                label = f"Person_{int(m2.group(1)):03d}" if m2 else None
            if label is None:
                m3 = re.search(r"(Person_\d+)", name, re.IGNORECASE)
                label = m3.group(1) if m3 else None
            if not label:
                continue
            out.append((p, label))
    if limit and limit > 0:
        # 分层采样：每人至少 1 张
        by_label: Dict[str, List[Tuple[Path, str]]] = defaultdict(list)
        for item in out:
            by_label[item[1]].append(item)
        picked = []
        per = max(1, limit // max(1, len(by_label)))
        for lbl, items in by_label.items():
            picked.extend(items[:per])
        if len(picked) < limit:
            remain = [x for x in out if x not in picked]
            picked += remain[: limit - len(picked)]
        out = picked
    return out


def scan_widerface(limit: int) -> List[Path]:
    base = DATA / "WIDERFACE"
    out: List[Path] = []
    if not base.exists():
        return out
    for ext in ["*.jpg", "*.png"]:
        for p in base.rglob(ext):
            out.append(p)
    if limit and limit > 0:
        out = out[:limit]
    return out


# ======================================================================
# 1. 检测器评估（用 WIDER FACE 测小脸/多人/模糊 表现）
# ======================================================================
def eval_detection(engine: FaceEngine, images: List[Path]) -> List[Dict]:
    rows = []
    for p in images:
        try:
            img = cv2.imread(str(p))
            if img is None:
                continue
            t0 = time.time()
            faces = engine.detect_and_extract(img, min_face_size=40, compute_embedding=False)
            ms = int((time.time() - t0) * 1000)
            h, w = img.shape[:2]
            avg_q = np.mean([f.quality_score for f in faces]) if faces else 0.0
            usable = sum(1 for f in faces if f.usable)
            rows.append({
                "image": str(p.relative_to(DATA)) if DATA in p.parents else p.name,
                "width": w, "height": h,
                "detected": len(faces),
                "usable": usable,
                "avg_quality": round(float(avg_q), 3),
                "latency_ms": ms,
            })
        except Exception as e:
            rows.append({"image": p.name, "error": str(e)})
    return rows


# ======================================================================
# 2. 1:1 匹配评估 (DrivFace 正/负样本对)
# ======================================================================
def eval_1to1(engine: FaceEngine, labeled: List[Tuple[Path, str]],
              num_pairs: int = 3000) -> Tuple[List[Dict], np.ndarray, np.ndarray]:
    """
    返回:
      rows: 每条样本对 (label, sim, is_genuine)
      y_true, y_score: 二分类 sklearn 格式
    """
    # 先提取每图的第一个可用人脸向量
    probe_feats: List[Tuple[str, np.ndarray]] = []  # (label, vec)
    for p, label in labeled:
        try:
            img = cv2.imread(str(p))
            if img is None:
                continue
            faces = engine.detect_and_extract(img, min_face_size=40, compute_embedding=True)
            for f in faces:
                if f.usable and f.embedding is not None:
                    probe_feats.append((label, f.embedding))
                    break
        except Exception:
            continue

    rows: List[Dict] = []
    if len(probe_feats) < 2:
        return rows, np.array([]), np.array([])

    # 构建正样本对（同一身份不同图片）和负样本对（不同身份）
    by_id: Dict[str, List[int]] = defaultdict(list)
    for i, (lbl, _) in enumerate(probe_feats):
        by_id[lbl].append(i)

    rng = np.random.RandomState(42)
    genuines = 0
    impostors = 0
    target = max(100, num_pairs // 2)

    # 正样本
    for lbl, idxs in by_id.items():
        if len(idxs) < 2:
            continue
        for _ in range(target // len(by_id) + 2):
            i, j = rng.choice(idxs, size=2, replace=False)
            sim = cosine_similarity(probe_feats[i][1], probe_feats[j][1])
            rows.append({"label_a": lbl, "label_b": lbl, "similarity": round(sim, 4), "is_genuine": 1})
            genuines += 1
            if genuines >= target:
                break
        if genuines >= target:
            break

    # 负样本
    ids = list(by_id.keys())
    while impostors < max(genuines, target):
        la, lb = rng.choice(ids, size=2, replace=False)
        ia = rng.choice(by_id[la])
        ib = rng.choice(by_id[lb])
        sim = cosine_similarity(probe_feats[ia][1], probe_feats[ib][1])
        rows.append({"label_a": la, "label_b": lb, "similarity": round(sim, 4), "is_genuine": 0})
        impostors += 1

    y_true = np.array([r["is_genuine"] for r in rows], dtype=np.int32)
    y_score = np.array([r["similarity"] for r in rows], dtype=np.float32)
    return rows, y_true, y_score


# ======================================================================
# 3. 1:N 检索评估 (用 DrivFace：把每人前 K 张做注册，其余做 probe)
# ======================================================================
def eval_1toN(engine: FaceEngine, labeled: List[Tuple[Path, str]],
              refs_per_person: int = 3
              ) -> Tuple[ReferenceGallery, List[Dict], List[Dict]]:
    # 分库 / probe
    by_id: Dict[str, List[Path]] = defaultdict(list)
    for p, lbl in labeled:
        by_id[lbl].append(p)

    gallery = ReferenceGallery(top_k=5)
    probe_items: List[Tuple[Path, str]] = []
    for lbl, files in by_id.items():
        gallery.add_subject(external_code=lbl)
        ref_files = files[:refs_per_person]
        probe_files = files[refs_per_person:]
        for fp in ref_files:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            faces = engine.detect_and_extract(img, compute_embedding=True)
            for f in faces:
                if f.usable and f.embedding is not None:
                    gallery.add_reference(lbl, f.embedding)
                    break
        probe_items.extend((fp, lbl) for fp in probe_files)

    # 1:N 查询
    rows: List[Dict] = []
    cands_rows: List[Dict] = []
    hit1, hit5, total = 0, 0, 0
    for fp, true_lbl in probe_items:
        res = process_image(engine, gallery, str(fp))
        if res.error or not res.detections:
            continue
        total += 1
        for face, cands in zip(res.detections, res.candidates_by_face):
            if not cands:
                break
            top1 = cands[0]
            if top1.external_code == true_lbl:
                hit1 += 1
            if any(c.external_code == true_lbl for c in cands):
                hit5 += 1
            rows.append({
                "image": fp.name, "true_label": true_lbl,
                "top1_code": top1.external_code, "top1_sim": top1.similarity,
                "top1_band": top1.decision_band, "hit_top1": int(top1.external_code == true_lbl),
                "hit_top5": int(any(c.external_code == true_lbl for c in cands)),
                "quality": face.quality_score, "num_cands": len(cands),
            })
            for c in cands:
                cands_rows.append({
                    "image": fp.name, "true_label": true_lbl,
                    "cand_code": c.external_code, "rank": c.rank,
                    "similarity": c.similarity, "band": c.decision_band,
                    "is_match": int(c.external_code == true_lbl),
                })
            break  # 只看第一个可用人脸

    summary_1n = {
        "n_probe": total,
        "top1_hit": hit1,
        "top1_acc": round(hit1 / total, 4) if total else 0,
        "top5_hit": hit5,
        "top5_acc": round(hit5 / total, 4) if total else 0,
    }
    return gallery, cands_rows, [summary_1n]


# ======================================================================
# 4. ROC / DET 曲线
# ======================================================================
def draw_roc_det(y_true: np.ndarray, y_score: np.ndarray, out_dir: Path) -> Dict[str, float]:
    from sklearn.metrics import roc_curve, auc
    metrics = {}
    if len(y_true) == 0:
        metrics["note"] = "no matching pairs evaluated"
        return metrics

    # 相似度越高越正例：y_score 直接用 similarity
    fpr, tpr, thresholds = roc_curve(y_true, y_score)
    roc_auc = auc(fpr, tpr)
    metrics["AUC"] = round(float(roc_auc), 4)

    # EER (FMR ≈ FNMR 处)
    fnmr = 1 - tpr
    diff = np.abs(fpr - fnmr)
    idx = int(np.argmin(diff))
    eer = float(0.5 * (fpr[idx] + fnmr[idx]))
    metrics["EER"] = round(eer, 4)
    metrics["EER_threshold"] = round(float(thresholds[idx]), 4)

    # FMR@1e-3 / FNMR@FMR=0.001
    target_fmr = 1e-3
    if fpr[-1] >= target_fmr:
        k = next(i for i, v in enumerate(fpr) if v >= target_fmr)
        metrics["FNMR@FMR=0.001"] = round(float(fnmr[k]), 4)
        metrics["threshold@FMR=0.001"] = round(float(thresholds[k]), 4)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # ROC
        plt.figure(figsize=(6, 5))
        plt.plot(fpr, tpr, label=f"AUC = {roc_auc:.3f}")
        plt.plot([0, 1], [0, 1], "k--", alpha=0.5)
        plt.scatter([fpr[idx]], [tpr[idx]], s=40, c="red", zorder=3, label=f"EER = {eer:.3f}")
        plt.xlabel("FMR (False Match Rate)")
        plt.ylabel("True Match Rate")
        plt.title("ROC — 1:1 Face Verification")
        plt.xlim(0, 1); plt.ylim(0, 1.02)
        plt.grid(alpha=0.2); plt.legend()
        plt.tight_layout()
        plt.savefig(out_dir / "roc_curve.png", dpi=140)
        plt.close()

        # DET: 正态坐标轴简化版 (log-log FMR vs FNMR)
        fpr2 = fpr[(fpr > 1e-6) & (fnmr > 1e-6)]
        fnmr2 = fnmr[(fpr > 1e-6) & (fnmr > 1e-6)]
        if len(fpr2) > 10:
            plt.figure(figsize=(6, 5))
            plt.loglog(fpr2, fnmr2)
            plt.scatter([fpr[idx]], [fnmr[idx]], s=40, c="red", label=f"EER={eer:.3f}")
            plt.xlabel("FMR")
            plt.ylabel("FNMR")
            plt.title("DET Curve")
            plt.grid(which="both", alpha=0.2); plt.legend()
            plt.tight_layout()
            plt.savefig(out_dir / "det_curve.png", dpi=140)
            plt.close()
    except Exception as e:
        metrics["plot_error"] = str(e)

    return metrics


# ======================================================================
# 5. 可视化样例
# ======================================================================
def save_samples(engine: FaceEngine, gallery: ReferenceGallery,
                 drivface: List[Tuple[Path, str]], wider: List[Path], n: int = 8):
    # DrivFace 带候选标签
    for i, (p, lbl) in enumerate(drivface[:n]):
        img = cv2.imread(str(p))
        if img is None:
            continue
        res = process_image(engine, gallery, str(p))
        vis = draw_result(img, res)
        tag = "ok" if res.num_faces > 0 else "noface"
        cv2.imwrite(str(SAMPLES / f"drivface_{i:02d}_{tag}_{lbl}.jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # WIDER FACE 只做人脸检测展示
    for i, p in enumerate(wider[:n]):
        img = cv2.imread(str(p))
        if img is None:
            continue
        res = process_image(engine, ReferenceGallery(), str(p))
        vis = draw_result(img, res)
        cv2.imwrite(str(SAMPLES / f"wider_{i:02d}.jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 90])


# ======================================================================
# 主流程
# ======================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="跑完整数据（否则每个数据集限制数量）")
    parser.add_argument("--limit-driv", type=int, default=0, help="DrivFace 最大张数 (0=自动)")
    parser.add_argument("--limit-wider", type=int, default=0, help="WIDER FACE 最大张数 (0=自动)")
    args = parser.parse_args()

    limit_driv = args.limit_driv or (0 if args.full else 120)
    limit_wider = args.limit_wider or (0 if args.full else 200)

    print("=" * 64)
    print("第1周：算法验证 (InsightFace + DrivFace + WIDER FACE)")
    print("=" * 64)

    # 1. 初始化引擎
    print("\n[1/6] 初始化 FaceEngine ...")
    model_root = str(Path(__file__).resolve().parent.parent / "backend" / "models")
    engine = FaceEngine(providers=["CPUExecutionProvider"], model_root=model_root)
    print(f"      fallback = {engine._fallback}")

    # 2. 数据扫描
    print("\n[2/6] 扫描数据集 ...")
    drivface = scan_drivface(limit_driv)
    wider = scan_widerface(limit_wider)
    print(f"      DrivFace 样本: {len(drivface)}")
    print(f"      WIDER FACE:   {len(wider)}")
    if not drivface and not wider:
        print("  [!] 没有找到数据集。")
        print("      请先运行: python scripts/download_datasets.py")
        print("      或手动把图片放到 data/DrivFace 与 data/WIDERFACE 下。")
        print("      脚本将生成空报告，但不会中断。")

    # 3. 检测评估
    print("\n[3/6] 人脸检测评估 (WIDER FACE)...")
    det_rows = eval_detection(engine, wider or [p for p, _ in drivface])
    if det_rows:
        with open(OUT / "detection_stats.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(det_rows[0].keys()))
            w.writeheader(); w.writerows(det_rows)
        dct_list = [r for r in det_rows if "detected" in r]
        avg_ms = np.mean([r["latency_ms"] for r in dct_list]) if dct_list else 0
        avg_q = np.mean([r["avg_quality"] for r in dct_list]) if dct_list else 0
        usable_rate = (sum(r["usable"] for r in dct_list) / max(1, sum(r["detected"] for r in dct_list))) if dct_list else 0
        print(f"      图片数: {len(dct_list)}")
        print(f"      总检测人脸: {sum(r['detected'] for r in dct_list)}")
        print(f"      平均质量分: {avg_q:.3f}  |  可用率: {usable_rate:.2%}  |  平均延迟: {avg_ms:.0f} ms")

    # 4. 1:1 匹配
    print("\n[4/6] 1:1 匹配评估 (DrivFace)...")
    rows_1to1, y_true, y_score = eval_1to1(engine, drivface)
    if rows_1to1:
        with open(OUT / "matching_1to1.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_1to1[0].keys()))
            w.writeheader(); w.writerows(rows_1to1)
        print(f"      样本对数量: {len(rows_1to1)}")

    # 5. 1:N 检索
    print("\n[5/6] 1:N 检索评估 (DrivFace)...")
    gallery, cand_rows, summary_1n = eval_1toN(engine, drivface)
    if cand_rows:
        with open(OUT / "matching_1toN.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(cand_rows[0].keys()))
            w.writeheader(); w.writerows(cand_rows)
        with open(OUT / "summary_1toN.json", "w", encoding="utf-8") as f:
            json.dump(summary_1n, f, ensure_ascii=False, indent=2)
        print(f"      gallery: {len(gallery)} 人 / {gallery.num_embeddings()} 向量")
        print(f"      {summary_1n}")
    with open(OUT / "gallery.json", "w", encoding="utf-8") as f:
        json.dump({
            "num_subjects": len(gallery),
            "num_embeddings": gallery.num_embeddings(),
            "thresholds": {
                "high": gallery.th_high, "medium": gallery.th_medium, "low": gallery.th_low
            },
            "subjects": {
                code: {"subject_id": info["subject_id"],
                       "display_name": info["display_name"],
                       "ref_count": len(info["embeddings"])}
                for code, info in gallery.subjects.items()
            },
        }, f, ensure_ascii=False, indent=2)

    # 6. 画图 + 保存样例
    print("\n[6/6] ROC/DET 曲线 + 可视化样例 ...")
    metrics = draw_roc_det(y_true, y_score, OUT)

    if drivface or wider:
        save_samples(engine, gallery, drivface, wider, n=8)

    # 7. 生成 summary.txt
    summary_parts = [
        "=" * 64,
        "第1周：算法验证 —— 离线评测报告",
        "=" * 64,
        "",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"InsightFace fallback 模式: {engine._fallback}",
        "",
        "-- 数据集 --",
        f"  DrivFace  图片数: {len(drivface)}",
        f"  WIDER FACE 图片数: {len(wider)}",
        f"  参考库人员: {len(gallery)} 人 / {gallery.num_embeddings()} 向量",
        "",
        "-- 检测 (WIDER FACE) --",
        f"  评估图片数:        {len(det_rows)}",
        f"  检测人脸总数:      {sum(r.get('detected',0) for r in det_rows)}",
        f"  可用人脸比例:      {usable_rate:.2%}",
        f"  平均质量分:        {avg_q:.3f}",
        f"  p50 处理延迟 ms:   {np.percentile([r.get('latency_ms',0) for r in det_rows], 50):.0f}",
        f"  p95 处理延迟 ms:   {np.percentile([r.get('latency_ms',0) for r in det_rows], 95):.0f}",
        "",
        "-- 1:1 验证 (DrivFace) --",
        f"  正负样本对: {len(rows_1to1)}",
    ]
    for k, v in metrics.items():
        summary_parts.append(f"  {k}: {v}")
    summary_parts += [
        "",
        "-- 1:N 检索 (DrivFace) --",
    ]
    if summary_1n:
        s = summary_1n[0]
        summary_parts += [
            f"  Probe 图片数:      {s['n_probe']}",
            f"  Top-1 命中率:      {s['top1_acc']:.2%}  ({s['top1_hit']}/{s['n_probe']})",
            f"  Top-5 命中率:      {s['top5_acc']:.2%}  ({s['top5_hit']}/{s['n_probe']})",
            "",
            f"  每千张图片候选数 (均值): {np.mean([r.get('num_cands',0) for r in det_rows] or [0]):.2f}",
        ]
    summary_parts += [
        "",
        "-- 注意事项 --",
        "  * DrivFace 仅 4 人，规模有限；结果只代表 4 分类，并不具备大规模场景可信度。",
        "  * 若使用了 fallback 模式（未安装 InsightFace），特征由颜色直方图构造，不具备识别能力。",
        "  * 接入 DriveFace / iCarB-Face 后请重新运行此脚本以更新报告。",
        "  * 阈值 (high/medium/low = {}/{}/{}) 来自默认配置，应用前需在真实授权数据上校准。".format(
            gallery.th_high, gallery.th_medium, gallery.th_low),
        "",
        "=" * 64,
    ]
    with open(OUT / "summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(summary_parts))

    print("\n".join(summary_parts))
    print(f"\n✅ 报告输出至: {OUT}")
    print(f"   summary.txt | detection_stats.csv | matching_1to1.csv | matching_1toN.csv")
    print(f"   roc_curve.png | det_curve.png | samples/ | gallery.json")


if __name__ == "__main__":
    main()
