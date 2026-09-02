"""
将评测结果写入数据库 (evaluation_runs 表)

用法: python scripts/write_eval_results.py
读取 output/week1/ 下的评测结果，调用后端 API 写入数据库。
"""
import json
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "week1"
API_BASE = "http://127.0.0.1:9091"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    # 读取评测产物
    summary_path = OUT / "summary.txt"
    summary_1to1_path = OUT / "matching_1to1.csv"
    summary_1toN_path = OUT / "summary_1toN.json"
    gallery_path = OUT / "gallery.json"

    if not summary_path.exists():
        print(f"[ERROR] {summary_path} 不存在，请先运行 week1_algorithm_validation.py")
        return

    # 解析 summary.txt 提取指标
    summary_text = summary_path.read_text(encoding="utf-8")

    # 提取关键指标
    metrics = {}
    for line in summary_text.split("\n"):
        line = line.strip()
        if line.startswith("AUC:"):
            metrics["AUC"] = float(line.split(":")[1].strip())
        elif line.startswith("EER:"):
            metrics["EER"] = float(line.split(":")[1].strip())
        elif line.startswith("FNMR@FMR=0.001:"):
            metrics["FNMR_at_FMR001"] = float(line.split(":")[1].strip())

    # 加载 1:N 结果
    if summary_1toN_path.exists():
        n1 = load_json(summary_1toN_path)
        if n1:
            metrics["top1"] = n1[0]["top1_acc"]
            metrics["top5"] = n1[0]["top5_acc"]
            metrics["total_probes"] = n1[0]["n_probe"]
            metrics["top1_hit"] = n1[0]["top1_hit"]
            metrics["top5_hit"] = n1[0]["top5_hit"]

    # 计算误报统计
    csv_path = OUT / "matching_1to1.csv"
    false_accepts = 0
    false_rejects = 0
    total_pairs = 0
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            import csv
            reader = csv.DictReader(f)
            for row in reader:
                total_pairs += 1
                is_genuine = int(row["is_genuine"])
                sim = float(row["similarity"])
                threshold = metrics.get("EER_threshold", 0.3)
                if is_genuine == 0 and sim >= threshold:
                    false_accepts += 1
                if is_genuine == 1 and sim < threshold:
                    false_rejects += 1

    metrics["false_accepts"] = false_accepts
    metrics["false_rejects"] = false_rejects
    metrics["total_pairs"] = total_pairs

    # 从 summary.txt 解析延迟
    for line in summary_text.split("\n"):
        if "p50 处理延迟" in line:
            import re
            m = re.search(r"([\d.]+)", line.split("ms:")[-1])
            if m:
                metrics["latency_p50"] = float(m.group(1))
        if "p95 处理延迟" in line:
            import re
            m = re.search(r"([\d.]+)", line.split("ms:")[-1])
            if m:
                metrics["latency_p95"] = float(m.group(1))

    # 组装评测数据
    eval_data = {
        "dataset_name": "DrivFace + WIDER FACE (Week 1)",
        "model_version": "insightface-buffalo-l-v1",
        "split_definition": "DrivFace: 4人, 每人3张参考, 其余probe; WIDER FACE: 100张检测评估",
        "metrics_json": metrics,
        "summary": f"第1周评测：DrivFace 600张 + WIDER FACE 100张。"
                   f"Top-1={metrics.get('top1', 0):.2%}, AUC={metrics.get('AUC', 0):.4f}, "
                   f"EER={metrics.get('EER', 0):.4f}。"
                   f"DrivFace仅4人，规模有限，接入DriveFace/iCarB-Face后重新评测。",
        "status": "success",
    }

    # 调用 API 写入
    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/evaluation/runs",
            data={
                "dataset_name": eval_data["dataset_name"],
                "model_version": eval_data["model_version"],
                "split_definition": eval_data["split_definition"],
            },
            files={
                "metrics_file": (
                    "metrics.json",
                    json.dumps(metrics, ensure_ascii=False).encode("utf-8"),
                    "application/json",
                )
            },
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"[OK] 评测结果已写入数据库，run_id={resp.json().get('id')}")
            print(f"     指标: AUC={metrics.get('AUC')}, EER={metrics.get('EER')}, "
                  f"Top1={metrics.get('top1')}, Top5={metrics.get('top5')}")
        else:
            print(f"[ERROR] API 返回 {resp.status_code}: {resp.text}")
    except requests.exceptions.ConnectionError:
        print("[ERROR] 后端未启动，请先运行 backend/app/main.py (端口 9091)")
        print("       或者直接用 SQL 插入 evaluation_runs 表")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
