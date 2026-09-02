"""使用 examples/demo_data 做本地接口级冒烟测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
API = os.getenv("FACE_API_URL", "http://127.0.0.1:9091").rstrip("/")
USERNAME = os.getenv("FACE_DEMO_USERNAME", "admin")
PASSWORD = os.getenv("FACE_DEMO_PASSWORD", "")
DATA = ROOT / "examples" / "demo_data"


def post_file(path: Path, endpoint: str, data: dict, headers: dict):
    with path.open("rb") as fh:
        return requests.post(
            f"{API}{endpoint}", data=data,
            files={"file": (path.name, fh, "image/jpeg")},
            headers=headers, timeout=180,
        )


def main() -> None:
    if not PASSWORD:
        raise SystemExit("请设置 FACE_DEMO_PASSWORD（本地管理员密码）后再运行")
    login = requests.post(f"{API}/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    project = requests.post(
        f"{API}/api/v1/projects",
        data={"name": "最小演示数据项目", "purpose": "接口级流程冒烟测试"},
        headers=headers, timeout=30,
    )
    project.raise_for_status()
    project_id = project.json()["id"]

    watchlist = manifest["watchlist"]
    for subject in watchlist:
        code = subject["code"]
        response = requests.post(
            f"{API}/api/v1/subjects/batch",
            json={"project_id": project_id, "items": [{"external_code": code, "display_name": code}]},
            headers=headers, timeout=30,
        )
        response.raise_for_status()

    imported = 0
    for subject in watchlist:
        code = subject["code"]
        for rel in subject["references"]:
            path = DATA / rel
            response = post_file(path, "/api/v1/references/upload", {"project_id": project_id, "external_code": code}, headers)
            response.raise_for_status()
            imported += 1

    probe_ids = []
    # 每个对象上传一张单人图，另加未知和三张多人合成图，覆盖完整演示链路。
    probe_paths = [subject["probes"][0] for subject in watchlist]
    probe_paths.extend(manifest.get("unknown", []))
    probe_paths.extend(item["path"] for item in manifest.get("composite", []))
    for rel in probe_paths:
        response = post_file(DATA / rel, "/api/v1/probes/upload", {"project_id": project_id, "source_type": "demo"}, headers)
        response.raise_for_status()
        probe_ids.append(response.json()["probe_id"])
    results = []
    for probe_id in probe_ids:
        detail = requests.get(f"{API}/api/v1/probes/{probe_id}", headers=headers, timeout=30)
        detail.raise_for_status()
        body = detail.json()
        results.append({"probe_id": probe_id, "status": body.get("processing_status"), "detected_faces": len(body.get("detections") or [])})
    result = {"project_id": project_id, "probe_ids": probe_ids, "imported_references": imported, "probes": results}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
