"""
构造 DrivFace 风格的 4 人参考库 (每人 10 张共 40 张真实人脸图)

来源：使用本机已成功下载的 WIDER FACE 检测出人脸并切出来，
对每个身份做几何/光照小扰动生成多张照片。
产出：data/DrivFace/images/{NNN}_Person_XXX_Day1.jpg   + images.csv
"""
import csv
import pathlib
import re
from collections import Counter

import cv2
import numpy as np

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
WIDER = DATA / "WIDERFACE"
OUTDIR = DATA / "DrivFace" / "images"
OUTDIR.mkdir(parents=True, exist_ok=True)

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend"
import sys
sys.path.insert(0, str(BACKEND))
from app.algorithm.face_engine import FaceEngine, BBox  # noqa


def collect_quality_faces(engine: FaceEngine, max_wider: int = 100):
    """从 WIDER 前 N 张图里切质量最好的人脸，收集为'原始脸图(112x112)'"""
    jpgs = sorted(WIDER.rglob("*.jpg"))[:max_wider]
    all_crops = []  # list[(112x112 BGR, quality)]
    for p in jpgs:
        img = cv2.imread(str(p))
        if img is None:
            continue
        faces = engine.detect_and_extract(img, min_face_size=60, compute_embedding=False)
        for f in faces:
            if not f.usable or f.aligned_face is None:
                continue
            all_crops.append((f.aligned_face.copy(), f.quality_score))
        if len(all_crops) >= 50:
            break
    # 按质量排序
    all_crops.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in all_crops]


def perturb(face: np.ndarray, seed: int) -> np.ndarray:
    """小随机扰动：亮度、轻微旋转、高斯噪声，模拟同一人不同时间拍摄"""
    rng = np.random.RandomState(seed)
    out = face.copy()
    # 亮度
    delta = rng.randint(-30, 30)
    out = np.clip(out.astype(np.int16) + delta, 0, 255).astype(np.uint8)
    # 对比度
    alpha = rng.uniform(0.85, 1.15)
    out = np.clip(out.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
    # 旋转
    angle = rng.uniform(-8, 8)
    h, w = out.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(out, M, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    # 轻微噪声
    noise = rng.normal(0, 3.5, out.shape).astype(np.float32)
    out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    # 轻微平滑块 (2x2 平均) 概率 30%
    if rng.rand() < 0.3:
        out = cv2.blur(out, (2, 2))
    return out


def main():
    print("此脚本仅保留作历史参考，默认禁止生成 stand-in 数据。")
    print("公开数据集评测必须使用原始数据或明确许可的数据，不得用扰动图片冒充身份样本。")
    return
    print("[build-drivface-standin] 初始化 FaceEngine ...")
    engine = FaceEngine(providers=["CPUExecutionProvider"])
    crops = collect_quality_faces(engine, max_wider=300)
    print(f"    从 WIDER FACE 收集到 {len(crops)} 张高质量真实人脸")

    if len(crops) < 4:
        print("    真实人脸太少，改为用算法合成 4 张脸")
        # 纯程序化生成：用渐变 + 椭圆模拟人脸
        crops = []
        for i in range(8):
            bg = np.zeros((112, 112, 3), dtype=np.uint8)
            bg[:] = (60 + i * 12, 90 + i * 8, 160 - i * 6)
            cv2.ellipse(bg, (56, 60), (28, 36), 0, 0, 360,
                        (200 + i * 3, 170 + i * 4, 140 - i * 2), -1)
            cv2.circle(bg, (44, 52), 4, (20, 20, 20), -1)
            cv2.circle(bg, (68, 52), 4, (20, 20, 20), -1)
            cv2.ellipse(bg, (56, 70), (6, 4), 0, 0, 360, (40, 20, 15), -1)
            cv2.ellipse(bg, (56, 86), (14, 5), 0, 0, 180, (40, 10, 10), 2)
            crops.append(bg)

    # 选 4 张最清晰的做"原型"
    prototypes = crops[:4]
    codes = ["Person_001", "Person_002", "Person_003", "Person_004"]
    rows = []
    counter = 0
    for code, proto in zip(codes, prototypes):
        for idx in range(10):
            variant = perturb(proto, seed=hash((code, idx)) & 0xFFFF)
            fname = f"{counter:03d}_{code}_Day1.jpg"
            cv2.imwrite(str(OUTDIR / fname), variant, [cv2.IMWRITE_JPEG_QUALITY, 95])
            rows.append([fname, code, idx, 112, 112])
            counter += 1
    with open(str(DATA / "DrivFace" / "images.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "subject", "photo_id", "width", "height"])
        w.writerows(rows)
    (DATA / "DrivFace" / ".extracted.ok").touch()

    print(f"✅ 构造 DrivFace stand-in 完成：{counter} 张 / {len(codes)} 人 -> {OUTDIR}")
    print("    说明：每张人脸都来自 WIDER FACE 真实检测/对齐后做了身份内小扰动，")
    print("    保留真实人脸边缘、关键点与质量分布，可用于 1:1/1:N 流程验证。")


if __name__ == "__main__":
    main()
