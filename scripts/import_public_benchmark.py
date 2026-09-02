"""将 public_benchmark.py 生成的摘要导入本地评测记录。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", default="output/public_benchmark/summary.json")
    parser.add_argument("--api", default="http://127.0.0.1:9091")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics = dict(summary.get("metrics") or {})
    # 前端统一读取大写指标名；公开评测脚本使用小写键，导入时做一次明确映射。
    if "auc" in metrics:
        metrics["AUC"] = metrics["auc"]
    if "eer" in metrics:
        metrics["EER"] = metrics["eer"]
    if "fnmr_at_fmr_0_001" in metrics:
        metrics["FNMR_at_FMR001"] = metrics["fnmr_at_fmr_0_001"]
    if "pairs" in metrics:
        metrics["total_pairs"] = metrics["pairs"]
    metrics.update({
        "protocol": summary.get("protocol"),
        "dataset": summary.get("dataset"),
        "num_subjects": summary.get("num_subjects"),
        "total_images": summary.get("dataset_images") or summary.get("images_scanned") or summary.get("images_embedded"),
        "total_probes": summary.get("probe_images") or summary.get("pairs_scored"),
        "embedded_images": summary.get("embedded_images"),
        "limitations": summary.get("limitations", []),
    })
    payload = {
        "dataset_name": f"{summary.get('dataset', '公开数据集')} 公开基线",
        "model_version": summary.get("model", "unknown"),
        "split_definition": summary.get("protocol"),
        "metrics_file": ("metrics.json", json.dumps(metrics, ensure_ascii=False), "application/json"),
    }
    response = requests.post(f"{args.api}/api/v1/evaluation/runs", files={"metrics_file": payload["metrics_file"]}, data={
        "dataset_name": payload["dataset_name"],
        "model_version": payload["model_version"],
        "split_definition": payload["split_definition"],
    }, timeout=30)
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
