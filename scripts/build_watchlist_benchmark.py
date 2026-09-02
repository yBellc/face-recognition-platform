"""构建匿名的“重点关注对象”流程验证集。

数据来自 LFW，但不使用真实姓名作为业务身份：选中的身份会被映射为 PO-001、PO-002 …。
每个对象拆成 enrollment/reference 和 probe；另选一组不入库身份作为 unknown。
同时生成 2~4 人组合图，用于验证一张图片多张脸的处理链路。
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent


def choose_people(image_root: Path, watchlist_count: int, background_count: int):
    people = []
    for d in sorted(image_root.iterdir() if image_root.exists() else []):
        if not d.is_dir():
            continue
        images = sorted(d.glob("*.jpg"))
        if len(images) >= 8:
            people.append((d.name, images))
    if len(people) < watchlist_count + background_count:
        raise RuntimeError(f"LFW 可用身份不足：需要 {watchlist_count + background_count}，实际 {len(people)}")
    # 固定选取，便于复现实验；不把真实姓名写进输出清单。
    watch = people[:watchlist_count]
    background = people[watchlist_count:watchlist_count + background_count]
    return watch, background


def copy_image(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def make_composite(items, out_path: Path, width=960, height=360):
    canvas = Image.new("RGB", (width, height), (245, 247, 250))
    cell_w = width // len(items)
    for idx, src in enumerate(items):
        with Image.open(src).convert("RGB") as img:
            fitted = ImageOps.contain(img, (cell_w - 16, height - 16))
            x = idx * cell_w + (cell_w - fitted.width) // 2
            y = (height - fitted.height) // 2
            canvas.paste(fitted, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=95)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist-count", type=int, default=8)
    ap.add_argument("--background-count", type=int, default=8)
    ap.add_argument("--references-per-person", type=int, default=3)
    ap.add_argument("--probes-per-person", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    image_root = ROOT / "data" / "LFW" / "lfw"
    out = ROOT / "data" / "watchlist_benchmark"
    if out.exists():
        shutil.rmtree(out)
    (out / "enrollment").mkdir(parents=True, exist_ok=True)
    (out / "probe").mkdir(parents=True, exist_ok=True)
    (out / "unknown").mkdir(parents=True, exist_ok=True)
    (out / "composite_probe").mkdir(parents=True, exist_ok=True)

    watch, background = choose_people(image_root, args.watchlist_count, args.background_count)
    manifest = {
        "name": "LFW anonymized watchlist workflow benchmark",
        "seed": args.seed,
        "watchlist": [],
        "unknown_probe": [],
        "composite_probe": [],
        "protocol": "enrollment/reference images are disjoint from probe images; unknown identities never enter gallery",
        "limitations": [
            "LFW is a general web-photo benchmark, not a real operational watchlist.",
            "Composite probes are synthetic multi-face compositions for pipeline testing only.",
            "All business labels are anonymized PO codes; source identity names are not exported.",
        ],
    }

    for i, (_source_name, images) in enumerate(watch, start=1):
        code = f"PO-{i:03d}"
        ref_imgs = images[:args.references_per_person]
        probe_imgs = images[args.references_per_person:args.references_per_person + args.probes_per_person]
        ref_rel, probe_rel = [], []
        for j, src in enumerate(ref_imgs, start=1):
            dst = out / "enrollment" / code / f"ref_{j:02d}.jpg"
            copy_image(src, dst)
            ref_rel.append(str(dst.relative_to(ROOT)))
        for j, src in enumerate(probe_imgs, start=1):
            dst = out / "probe" / code / f"probe_{j:02d}.jpg"
            copy_image(src, dst)
            probe_rel.append(str(dst.relative_to(ROOT)))
        manifest["watchlist"].append({"code": code, "references": ref_rel, "probes": probe_rel})

    for i, (_source_name, images) in enumerate(background, start=1):
        code = f"UNKNOWN-{i:03d}"
        for j, src in enumerate(images[:args.probes_per_person], start=1):
            dst = out / "unknown" / code / f"probe_{j:02d}.jpg"
            copy_image(src, dst)
            manifest["unknown_probe"].append({"code": code, "path": str(dst.relative_to(ROOT))})

    watch_probe_paths = [ROOT / x["probes"][0] for x in manifest["watchlist"]]
    unknown_paths = [ROOT / x["path"] for x in manifest["unknown_probe"]]
    composites = [
        (watch_probe_paths[:2], [x["code"] for x in manifest["watchlist"][:2]]),
        ([watch_probe_paths[0], unknown_paths[0], watch_probe_paths[2]],
         [manifest["watchlist"][0]["code"], "UNKNOWN-001", manifest["watchlist"][2]["code"]]),
        (unknown_paths[:3], ["UNKNOWN-001", "UNKNOWN-002", "UNKNOWN-003"]),
    ]
    for i, (items, labels) in enumerate(composites, start=1):
        dst = out / "composite_probe" / f"composite_{i:02d}.jpg"
        make_composite(items, dst)
        manifest["composite_probe"].append({"path": str(dst.relative_to(ROOT)), "components": labels})

    manifest["counts"] = {
        "watchlist_subjects": len(manifest["watchlist"]),
        "unknown_subjects": args.background_count,
        "reference_images": sum(len(x["references"]) for x in manifest["watchlist"]),
        "watchlist_probe_images": sum(len(x["probes"]) for x in manifest["watchlist"]),
        "unknown_probe_images": len(manifest["unknown_probe"]),
        "composite_probe_images": len(manifest["composite_probe"]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
