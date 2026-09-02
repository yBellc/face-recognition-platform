"""将匿名 watchlist benchmark 注册到本地项目并执行多人脸上传冒烟测试。"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:9091"


def main():
    manifest_path = ROOT / "data" / "watchlist_benchmark" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project = requests.post(
        f"{API}/api/v1/projects",
        data={"name": "公开数据重点对象流程验证", "purpose": "LFW 匿名多人脸检索冒烟测试"},
        timeout=30,
    ).json()
    project_id = project["id"]
    items = [{"external_code": x["code"], "display_name": x["code"]} for x in manifest["watchlist"]]
    requests.post(f"{API}/api/v1/subjects/batch", json={"project_id": project_id, "items": items}, timeout=30).raise_for_status()

    registered, errors = 0, []
    for subject in manifest["watchlist"]:
        for rel in subject["references"]:
            path = ROOT / rel
            with path.open("rb") as fh:
                response = requests.post(
                    f"{API}/api/v1/references/upload",
                    data={"project_id": project_id, "external_code": subject["code"]},
                    files={"file": (path.name, fh, "image/jpeg")},
                    timeout=90,
                )
            if response.ok:
                registered += 1
            else:
                errors.append({"path": rel, "status": response.status_code, "body": response.text[:300]})

    probes = []
    for item in manifest["composite_probe"]:
        path = ROOT / item["path"]
        with path.open("rb") as fh:
            response = requests.post(
                f"{API}/api/v1/probes/upload",
                data={"project_id": project_id, "source_type": "public_benchmark"},
                files={"file": (path.name, fh, "image/jpeg")},
                timeout=180,
            )
        response.raise_for_status()
        probes.append({"probe_id": response.json()["probe_id"], "expected_components": item["components"]})

    results = []
    for probe in probes:
        detail = requests.get(f"{API}/api/v1/probes/{probe['probe_id']}", timeout=30).json()
        candidates = requests.get(f"{API}/api/v1/candidates", params={"project_id": project_id, "limit": 1000}, timeout=30).json()
        grouped = defaultdict(list)
        for candidate in candidates:
            if candidate.get("probe_id") == probe["probe_id"]:
                grouped[candidate.get("probe_face_id")].append(candidate)
        results.append({
            "probe_id": probe["probe_id"],
            "expected_components": probe["expected_components"],
            "status": detail.get("processing_status"),
            "detected_faces": len(detail.get("detections") or []),
            "candidate_faces": len(grouped),
            "top_candidates": [
                {"probe_face_id": face_id, "subject_code": rows[0].get("subject_code"), "similarity": rows[0].get("similarity"), "decision_band": rows[0].get("decision_band")}
                for face_id, rows in grouped.items()
            ],
        })
    summary = {"project_id": project_id, "registered_references": registered, "registration_errors": errors, "probes": results}
    out = ROOT / "output" / "public_benchmark"
    out.mkdir(parents=True, exist_ok=True)
    (out / "watchlist_smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
