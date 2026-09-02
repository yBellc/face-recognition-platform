"""
用 LFW (Labeled Faces in the Wild) 扩充人员库
LFW 是最经典的公开人脸识别数据集，5749 人，可直接下载

步骤：
1. 下载 LFW-deepfunneled (约 200MB)
2. 每人取前 3 张作为参考图
3. 每人取第 4 张作为 probe 测试
4. 通过 API 注册到系统中

使用：python scripts/setup_lfw_dataset.py
"""
import os
import sys
import time
import zipfile
import shutil
import urllib.request
import ssl
from pathlib import Path

import requests

ssl._create_default_https_context = ssl._create_unverified_context

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LFW_DIR = DATA / "LFW"
TMP = DATA / "_tmp"
TMP.mkdir(exist_ok=True)

BASE_URL = "http://127.0.0.1:9091"
API_BASE = f"{BASE_URL}/api/v1"


def download_lfw():
    """下载 LFW-deepfunneled (200MB)"""
    target = TMP / "lfw-deepfunneled.zip"
    if target.exists() and target.stat().st_size > 100_000_000:
        print(f"✓ LFW zip 已存在: {target}")
        return target

    # LFW 官方下载
    urls = [
        "http://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.zip",
        "https://pipilab-static.library.ucsc.edu/public/lfw/lfw-deepfunneled.zip",
    ]

    for url in urls:
        print(f"尝试下载: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", "0") or 0)
                downloaded = 0
                chunk_size = 1024 * 1024  # 1MB
                with open(target, "wb") as f:
                    while True:
                        buf = resp.read(chunk_size)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        if total:
                            pct = downloaded / total * 100
                            mb = downloaded // 1024 // 1024
                            total_mb = total // 1024 // 1024
                            print(f"\r  下载中 {mb}MB / {total_mb}MB ({pct:.1f}%)", end="")
                print()
            print(f"✓ 下载完成: {target}")
            return target
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            if target.exists():
                target.unlink()

    print("✗ 所有下载源都失败了")
    return None


def extract_lfw(zip_path: Path):
    """解压 LFW"""
    if LFW_DIR.exists() and list(LFW_DIR.rglob("*.jpg")):
        count = len(list(LFW_DIR.rglob("*.jpg")))
        print(f"✓ LFW 已解压，共 {count} 张图片")
        return

    print(f"解压 {zip_path} -> {LFW_DIR}")
    LFW_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # 只解压 jpg 文件
        members = [m for m in zf.namelist() if m.endswith(".jpg")]
        print(f"  共 {len(members)} 张 jpg")
        zf.extractall(LFW_DIR, members=members)

    count = len(list(LFW_DIR.rglob("*.jpg")))
    print(f"✓ 解压完成，共 {count} 张图片")


def collect_persons(max_persons=80, min_images_per_person=3):
    """
    收集人员数据
    返回: [(person_name, [img_paths...]), ...]
    """
    print(f"\n收集人员数据 (最多 {max_persons} 人，每人至少 {min_images_per_person} 张)")

    # LFW 目录结构: LFW/lfw-deepfunneled/{姓名}/{姓名}_{序号}.jpg
    # 或直接: LFW/{姓名}/{姓名}_{序号}.jpg
    persons = {}
    for jpg in LFW_DIR.rglob("*.jpg"):
        # 解析姓名: 上级目录名
        parent = jpg.parent
        person_name = parent.name

        # 跳过 lfw-deepfunneled 根目录
        if person_name in ("lfw-deepfunneled", ""):
            continue

        if person_name not in persons:
            persons[person_name] = []
        persons[person_name].append(str(jpg))

    # 筛选: 至少有 min_images_per_person 张的人
    qualified = []
    for name, paths in sorted(persons.items()):
        if len(paths) >= min_images_per_person:
            # 按文件名排序（序号从小到大）
            paths.sort()
            qualified.append((name, paths))

    print(f"  总人员数: {len(persons)}")
    print(f"  合格人员 (>={min_images_per_person}张): {len(qualified)}")

    # 取前 max_persons 人
    qualified = qualified[:max_persons]
    print(f"  选取前 {len(qualified)} 人")

    for name, paths in qualified[:5]:
        print(f"    {name}: {len(paths)} 张")

    return qualified


def register_to_system(persons_data, project_id=1, images_per_person=3):
    """
    将人员数据注册到系统
    每人取前 images_per_person 张作参考图，第 images_per_person+1 张作 probe
    """
    print(f"\n注册到系统 (项目 {project_id})")
    print(f"  人员数: {len(persons_data)}")

    success_count = 0
    probe_count = 0
    skipped = 0
    ref_count = 0

    for idx, (name, paths) in enumerate(persons_data):
        # 生成匿名编号 (Person_005 起始，因为已有 001-004)
        person_num = idx + 5
        external_code = f"Person_{person_num:03d}"
        display_name = name.replace("_", " ")

        try:
            # 1. 创建人员 (JSON)
            r = requests.post(
                f"{API_BASE}/subjects",
                json={
                    "project_id": project_id,
                    "external_code": external_code,
                    "display_name": display_name,
                },
                timeout=10,
            )
            if r.status_code not in (200, 201):
                print(f"  [{external_code}] 创建人员失败: {r.status_code} {r.text[:100]}")
                skipped += 1
                continue

            # 2. 上传参考图 (Form: project_id, external_code, file)
            n_refs = min(images_per_person, len(paths) - 1)
            for i in range(n_refs):
                img_path = paths[i]
                with open(img_path, "rb") as f:
                    r = requests.post(
                        f"{API_BASE}/references/upload",
                        data={
                            "project_id": str(project_id),
                            "external_code": external_code,
                        },
                        files={"file": (os.path.basename(img_path), f, "image/jpeg")},
                        timeout=20,
                    )
                if r.status_code in (200, 201):
                    ref_count += 1
                # 失败不打印，太多了

            # 3. 创建 probe (Form: project_id, source_type, file)
            if len(paths) > images_per_person:
                probe_path = paths[images_per_person]
                with open(probe_path, "rb") as f:
                    r = requests.post(
                        f"{API_BASE}/probes/upload",
                        data={
                            "project_id": str(project_id),
                            "source_type": "lfw_dataset",
                        },
                        files={"file": (os.path.basename(probe_path), f, "image/jpeg")},
                        timeout=20,
                    )
                if r.status_code in (200, 201):
                    probe_count += 1

            success_count += 1

            if (idx + 1) % 10 == 0 or idx == len(persons_data) - 1:
                print(f"  进度: {idx + 1}/{len(persons_data)} (人员: {success_count}, 参考图: {ref_count}, probe: {probe_count}, 跳过: {skipped})")

        except Exception as e:
            print(f"  [{external_code}] 异常: {e}")
            skipped += 1

    print(f"\n✓ 注册完成: {success_count} 人成功, {ref_count} 张参考图, {probe_count} 个 probe, {skipped} 人跳过")


def main():
    print("=" * 60)
    print("LFW 数据集扩充脚本 — 从 4 人扩充到 80+ 人")
    print("=" * 60)

    # Step 0: 检查后端
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            print("✗ 后端未启动，请先启动后端: uvicorn app.main:app --port 9091")
            return
        health = r.json()
        print(f"✓ 后端已连接: {health.get('healthy')}")
    except Exception as e:
        print(f"✗ 无法连接后端: {e}")
        print("  请先运行: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 9091")
        return

    # Step 1: 下载 LFW
    print("\n--- Step 1: 下载 LFW ---")
    zip_path = download_lfw()
    if zip_path is None:
        print("无法下载 LFW。请手动下载 http://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.zip 到 data/_tmp/")
        print("或者运行: pip install gdown && gdown https://drive.google.com/uc?id=1PZs4q1klpzllbyiix3sNG5B4sXgaU5Ga")
        return

    # Step 2: 解压
    print("\n--- Step 2: 解压 ---")
    extract_lfw(zip_path)

    # Step 3: 收集人员
    print("\n--- Step 3: 收集人员 ---")
    persons_data = collect_persons(max_persons=80, min_images_per_person=4)

    if not persons_data:
        print("✗ 没有找到合格的人员数据")
        return

    # Step 4: 注册到系统
    print("\n--- Step 4: 注册到系统 ---")
    register_to_system(persons_data, project_id=1, images_per_person=3)

    # 总结
    total_refs = sum(min(3, len(paths) - 1) for _, paths in persons_data)
    total_probes = sum(1 for _, paths in persons_data if len(paths) > 3)
    print(f"\n{'='*60}")
    print(f"完成！人员库扩充:")
    print(f"  新增人员: {len(persons_data)} 人")
    print(f"  新增参考图: {total_refs} 张")
    print(f"  新增 probe: {total_probes} 张")
    print(f"  总人员数: {4 + len(persons_data)} 人")
    print(f"\n下一步: 重新运行评测脚本生成可信指标")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
