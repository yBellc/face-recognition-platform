"""
下载 InsightFace buffalo_l 预训练模型。
默认从 GitHub release 下载；如失败则尝试 HuggingFace / Gitee 镜像。

用户也可以手动下载 buffalo_l.zip (~100MB)，解压到:
    backend/models/buffalo_l/
或
    ~/.insightface/models/buffalo_l/

运行: python scripts/download_insightface_model.py
"""
from __future__ import annotations

import os
import sys
import zipfile
import shutil
import ssl
import urllib.request
from pathlib import Path

# 模型保存根目录
ROOT = Path(__file__).resolve().parent.parent / "backend" / "models"
MODEL_NAME = "buffalo_l"
ZIP_PATH = ROOT / f"{MODEL_NAME}.zip"
EXTRACT_PATH = ROOT / "models" / MODEL_NAME

# 候选下载源（按优先级）
URLS = [
    # 官方 GitHub release
    f"https://github.com/deepinsight/insightface/releases/download/v0.7/{MODEL_NAME}.zip",
    # HuggingFace mirror
    f"https://huggingface.co/pfrancesco/insightface-{MODEL_NAME}/resolve/main/{MODEL_NAME}.zip",
    # Gitee mirror
    f"https://gitee.com/pfrancesco/insightface-{MODEL_NAME}/resolve/main/{MODEL_NAME}.zip",
    # 另一个 HF 路径
    f"https://huggingface.co/MonsterMMORPG/tools_python/resolve/main/{MODEL_NAME}.zip",
]


def try_download(url: str, timeout: int = 120) -> bool:
    """尝试从单个 URL 下载，成功返回 True"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    print(f"  尝试: {url}")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length", "0") or 0)
            if total > 0:
                print(f"  响应: HTTP {resp.status}, 大小: {total / 1024 / 1024:.1f} MB")
            else:
                print(f"  响应: HTTP {resp.status} (chunked)")
            ROOT.mkdir(parents=True, exist_ok=True)
            with open(ZIP_PATH, "wb") as f:
                shutil.copyfileobj(resp, f)
            actual = ZIP_PATH.stat().st_size
            print(f"  下载完成: {actual / 1024 / 1024:.1f} MB")
            return actual > 10_000_000  # 至少 10MB
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
    return False


def download() -> bool:
    """按顺序尝试所有 URL，成功一个即返回"""
    for url in URLS:
        if try_download(url):
            return True
        if ZIP_PATH.exists():
            ZIP_PATH.unlink()
    return False


def extract() -> bool:
    """解压 zip 到目标目录"""
    if not ZIP_PATH.exists():
        print(f"[ERROR] zip 文件不存在: {ZIP_PATH}")
        return False
    print(f"解压 {ZIP_PATH} → {EXTRACT_PATH}")
    # 清理旧目录
    if EXTRACT_PATH.parent.exists():
        shutil.rmtree(EXTRACT_PATH.parent, ignore_errors=True)
    EXTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as z:
        names = z.namelist()
        print(f"  压缩包内文件数: {len(names)}")
        # 看看是否有嵌套的 buffalo_l 目录
        top_dirs = set(n.split("/")[0] for n in names if "/" in n)
        print(f"  顶层目录: {top_dirs}")
        z.extractall(EXTRACT_PATH.parent)
    # 检查解压结构
    files = list(EXTRACT_PATH.rglob("*.onnx"))
    print(f"  解压后 .onnx 文件数: {len(files)}")
    for f in files[:5]:
        print(f"    {f.relative_to(EXTRACT_PATH)}")
    # 清理 zip
    ZIP_PATH.unlink(missing_ok=True)
    return len(files) > 0


def main():
    print("=" * 50)
    print(f"下载 InsightFace buffalo_l 模型")
    print(f"保存路径: {ROOT}")
    print("=" * 50)

    # 检查是否已存在
    if EXTRACT_PATH.exists():
        onnx_files = list(EXTRACT_PATH.rglob("*.onnx"))
        if onnx_files:
            print(f"\n✅ 模型已存在: {EXTRACT_PATH} ({len(onnx_files)} 个 .onnx 文件)")
            return 0

    # 先尝试下载
    success = download()
    if not success:
        print("\n❌ 所有下载源都失败了。")
        print("📋 手动下载指引:")
        print(f"   1. 访问 https://github.com/deepinsight/insightface/releases/tag/v0.7")
        print(f"   2. 下载 buffalo_l.zip (~100MB)")
        print(f"   3. 解压到: {EXTRACT_PATH}")
        print(f"   4. 目录下应包含 *.onnx 文件")
        print("")
        print("   或使用 HuggingFace 镜像:")
        print("   访问 https://huggingface.co/pfrancesco/insightface-buffalo_l")
        print("   下载 buffalo_l.zip 后解压到上述路径")
        return 1

    # 解压
    if extract():
        print(f"\n✅ 模型准备完成！目录结构:")
        for p in sorted(EXTRACT_PATH.rglob("*")):
            if p.is_file():
                print(f"  {p.relative_to(EXTRACT_PATH)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
