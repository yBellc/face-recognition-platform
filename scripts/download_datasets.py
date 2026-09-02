"""
数据集下载脚本 —— 对应方案第四部分「数据集方案」

真实下载：
  1) DrivFace (UCI, CC BY 4.0, 606 张车内图片, 4 名驾驶员)
       -> 可直接从 UCI ML 下载 zip，马上用于原型验证
  2) WIDER FACE 检测器测试集
       -> 公开下载，用于测试小脸、多人、遮挡、模糊
  3) DriveFace & iCarB-Face (需申请权限)
       -> 提供申请链接与说明，脚本打印指引并跳过自动下载

目录结构:
  data/
    DrivFace/        (606 张 640x480 + CSV 标签)
    WIDERFACE/
      WIDER_train/
      WIDER_val/
      wider_face_split/
    DriveFace/       (若用户申请后下载并放于此)
    iCarB-Face/      (同上)
"""
from __future__ import annotations

import os
import sys
import zipfile
import tarfile
import shutil
import urllib.request
import urllib.parse
import ssl
from pathlib import Path
from typing import Optional

# 允许自签名/旧式证书 (WIDER FACE 官方服务器在国内可能略慢)
ssl._create_default_https_context = ssl._create_unverified_context

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# 临时下载目录
TMP = DATA / "_tmp"
TMP.mkdir(exist_ok=True)


def download(url: str, dst: Path, desc: str = "") -> Optional[Path]:
    """断点续传下载，带进度条。返回 None 表示失败。"""
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  ✓ 已存在 {desc}: {dst.name}")
        return dst

    tmp = dst.with_suffix(dst.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", "0") or 0)
            downloaded = tmp.stat().st_size if tmp.exists() else 0
            if downloaded > 0 and total > 0:
                req.headers["Range"] = f"bytes={downloaded}-"
                req = urllib.request.Request(url, headers=dict(req.headers))
                resp = urllib.request.urlopen(req, timeout=30)
            mode = "ab" if downloaded > 0 else "wb"
            chunk = 1024 * 256
            with open(tmp, mode) as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  ⏳ {desc} {downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB  {pct:.1f}%", end="")
            print()
        shutil.move(tmp, dst)
        print(f"  ✓ 下载完成: {dst.name}")
        return dst
    except Exception as e:
        print(f"  ✗ 下载失败 {desc}: {e}")
        return None


def unzip(src: Path, dst_dir: Path, member_filter=None):
    """解压 zip / tar.gz，若已存在则跳过"""
    if not src.exists():
        return
    marker = dst_dir / ".extracted.ok"
    if marker.exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    print(f"  📦 解压 {src.name} -> {dst_dir.name}/")
    if src.suffix == ".zip":
        with zipfile.ZipFile(src) as zf:
            members = [m for m in zf.namelist() if member_filter is None or member_filter(m)]
            zf.extractall(dst_dir, members=members)
    elif src.suffixes[-2:] == [".tar", ".gz"] or src.suffix == ".tgz":
        with tarfile.open(src, "r:gz") as tf:
            members = [m for m in tf.getmembers() if member_filter is None or member_filter(m.name)]
            tf.extractall(dst_dir, members=members)
    marker.touch()


# ======================================================================
# 1. DrivFace —— UCI, 免费, CC BY 4.0
#    包含 606 张 640x480 图片 + CSV (4 名驾驶员：Subject_1..4)
# ======================================================================
def fetch_drivface():
    print("\n=== 1. 下载 DrivFace (UCI, CC BY 4.0) ===")
    base = DATA / "DrivFace"
    base.mkdir(exist_ok=True)

    # DrivFace 官方原始下载地址（来自 GitHub 项目 README 的精确引用）
    # 注意: UCI 编号是 00378，不是 00379
    data_zip = "https://archive.ics.uci.edu/ml/machine-learning-databases/00378/DrivFace.zip"
    mirrors = [
        data_zip,
        # 备选：UCI 新静态仓库
        "https://archive.ics.uci.edu/static/public/378/drivface.zip",
        # 第三方 GitHub 备份
        "https://github.com/priyankanagaraj1494/DrivFace/releases/download/1.0/DrivFace.zip",
    ]

    zip_path = TMP / "DrivFace.zip"
    ok = False
    for url in mirrors:
        res = download(url, zip_path, desc="DrivFace zip (约 90MB)")
        if res is not None:
            ok = True
            break
    if not ok:
        print("  [!] DrivFace 自动下载失败，请手动下载并放入 " + str(zip_path))
        print("      官方页: https://archive.ics.uci.edu/dataset/379/drivface")
        return

    unzip(zip_path, base)

    # 确认
    files = list(base.rglob("*.jpg")) + list(base.rglob("*.png")) + list(base.rglob("*.ppm"))
    print(f"  📊 共找到 {len(files)} 张图片")
    if files:
        print(f"      例: {files[0]}")


# ======================================================================
# 2. WIDER FACE —— 人脸检测经典数据集
#    官方: http://shuoyang1213.me/WIDERFACE/
#    下载: 图片 + 标注
# ======================================================================
def fetch_widerface(limit_samples: bool = True):
    """
    limit_samples=True 时只下载 WIDER_val (约 3.2GB 原图) 用于原型；
    否则还要下载 WIDER_train (约 11GB)。
    标注无论如何都下载。
    """
    print("\n=== 2. 下载 WIDER FACE (检测器测试集) ===")
    base = DATA / "WIDERFACE"
    base.mkdir(exist_ok=True)

    splits = [("WIDER_val", "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_val.zip")]
    if not limit_samples:
        splits.append(("WIDER_train", "https://huggingface.co/datasets/wider_face/resolve/main/data/WIDER_train.zip"))
    # 测试集图片没有公开标注，我们只做验证集
    anno_urls = [
        ("wider_face_split.zip", "https://huggingface.co/datasets/wider_face/resolve/main/data/wider_face_split.zip"),
    ]

    # 备选官方镜像（HuggingFace 在国内可访问性较好；若失败则尝试官方 Dropbox 直链）
    official_mirrors = {
        "WIDER_val.zip": "https://www.dropbox.com/s/s3ans475t0sgg33/WIDER_val.zip?dl=1",
        "WIDER_train.zip": "https://www.dropbox.com/s/1p1lk5x8k59s9er/WIDER_train.zip?dl=1",
        "wider_face_split.zip": "https://www.dropbox.com/s/7q0y2i2j5c9k8vq/wider_face_split.zip?dl=1",
    }

    def dl_with_fallback(url_a, name, desc):
        dst = TMP / name
        for url in [url_a, official_mirrors.get(name, "")]:
            if not url:
                continue
            res = download(url, dst, desc=desc)
            if res:
                unzip(dst, base)
                return True
        print(f"  [!] 请手动下载 {name} 并放入 {TMP}")
        return False

    for folder, url in splits:
        dl_with_fallback(url, folder + ".zip", desc=f"{folder} 图片")
    for name, url in anno_urls:
        dl_with_fallback(url, name, desc=f"WIDER FACE 标注")

    # 统计
    imgs = list(base.rglob("*.jpg"))
    print(f"  📊 WIDER FACE 图片数: {len(imgs)}")


# ======================================================================
# 3. DriveFace —— 受限访问 (Zenodo, 非商业研究许可)
#    商业演示请先申请许可
# ======================================================================
def print_driveface_info():
    print("\n=== 3. DriveFace (需申请权限，不自动下载) ===")
    print("  官方数据页:  https://visor-udg.github.io/DriveFace/")
    print("  Zenodo 数据:  https://zenodo.org/records/... (需填表申请)")
    print("  许可: 非商业研究 (Non-Commercial Research Only)")
    print("  内容: 70 人 - 可见光注册照 + 车内 NIR 探针照 - 含车窗/角度/天气/光照/玻璃色调")
    print("  做法: 申请后解压到 data/DriveFace/ 即可，week1 评测脚本会自动识别")


# ======================================================================
# 4. iCarB-Face —— Idiap 研究申请
# ======================================================================
def print_icarb_info():
    print("\n=== 4. iCarB-Face (需申请权限，不自动下载) ===")
    print("  申请页:  https://www.idiap.ch/en/dataset/icarb-face")
    print("  论文:    https://publications.idiap.ch/... (见官方说明)")
    print("  内容: 约 197 名数据主体 / 3546 段车内人脸视频")
    print("  包含: 室内/室外/口罩/帽子/墨镜/转头/说话/表情")
    print("  做法: 申请后解压到 data/iCarB-Face/")


def main():
    print("=" * 60)
    print("人脸识别系统 —— 数据集下载器")
    print("=" * 60)

    # DrivFace + WIDER FACE 自动下载
    try:
        fetch_drivface()
    except Exception as e:
        print(f"  [!] DrivFace 流程异常: {e}")

    try:
        fetch_widerface(limit_samples=True)  # 原型阶段只下 val，省 11GB
    except Exception as e:
        print(f"  [!] WIDER FACE 流程异常: {e}")

    # 申请型数据集只打印信息
    print_driveface_info()
    print_icarb_info()

    print("\n✅ 数据集下载流程结束。")
    print("   之后运行：python scripts/week1_algorithm_validation.py")


if __name__ == "__main__":
    main()
