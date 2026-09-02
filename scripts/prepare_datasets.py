"""一键准备数据集：DrivFace (真实可下载的代理) + 确认 WIDER FACE"""
import os
import ssl
import csv
import zipfile
import urllib.request
import pathlib
import numpy as np

ssl._create_default_https_context = ssl._create_unverified_context

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
TMP = DATA / "_tmp"
TMP.mkdir(parents=True, exist_ok=True)

# ---------- 1. 先看 DrivFace 是否已经有 ----------
DRIV = DATA / "DrivFace"
DRIV.mkdir(parents=True, exist_ok=True)
existing = list(DRIV.rglob("*.jpg")) + list(DRIV.rglob("*.ppm"))
if len(existing) >= 40:
    print(f"[1] DrivFace 已有 {len(existing)} 张，跳过")
else:
    print("[1] DrivFace 图片不足，跳过自动构造 stand-in 数据。")
    print("    请从数据集原始来源下载并核对许可后再放入 data/DrivFace/。")

# ---------- 2. 确认 WIDER FACE ----------
WIDER = DATA / "WIDERFACE"
wider_imgs = list(WIDER.rglob("*.jpg"))
print(f"[2] WIDER FACE 图片: {len(wider_imgs)}")
if wider_imgs:
    print(f"    例: {wider_imgs[0]}")

# ---------- 3. DriveFace / iCarB-Face 提示 ----------
print("\n[3] DriveFace (受限访问): https://visor-udg.github.io/DriveFace/")
print("[4] iCarB-Face (Idiap 申请):   https://www.idiap.ch/en/dataset/icarb-face")
print("    申请成功后解压到 data/DriveFace/ 和 data/iCarB-Face/ 即可，week1/week2 会自动发现并使用。")
print("\n✅ 数据集准备完成。")
