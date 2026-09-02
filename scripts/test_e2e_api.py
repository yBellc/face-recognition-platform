"""端到端 API 测试脚本：InsightFace 真模型"""
import requests
import json
import time
from pathlib import Path

BASE = "http://127.0.0.1:9090"
session = requests.Session()

# 1. Dashboard
r = session.get(f"{BASE}/api/v1/dashboard")
print(f"Dashboard: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    mv = d.get("model_version", "N/A")
    th = d.get("thresholds", {})
    bc = d.get("band_counts", {})
    print(f"  model_version: {mv}")
    print(f"  thresholds: {json.dumps(th)}")
    print(f"  band_counts: {json.dumps(bc)}")

# 2. 创建项目
r = session.post(f"{BASE}/api/v1/projects", json={
    "name": "E2E Test",
    "description": "InsightFace E2E test",
})
print(f"\nCreate project: {r.status_code}")
if r.status_code == 200:
    proj = r.json()
    project_id = proj["id"]
    print(f"  project_id: {project_id}")
else:
    print(f"  body: {r.text[:200]}")
    project_id = 1

# 3. 列出 DrivFace 图片
driv_dir = Path("data/DrivFace")
images = sorted(driv_dir.rglob("*.jpg"))
print(f"\nDrivFace images: {len(images)} total, testing first 12")

# 4. 上传 3 张参考图 (同一人 Person_A)
print("\n--- Upload References (Person_A) ---")
for i, img_path in enumerate(images[:3]):
    with open(img_path, "rb") as f:
        r = session.post(f"{BASE}/api/v1/references/upload", data={
            "project_id": project_id,
            "external_code": f"Person_A_{i+1}",
        }, files={"file": (img_path.name, f, "image/jpeg")})
    status = "OK" if r.status_code == 200 else f"ERR {r.status_code}"
    detail = ""
    if r.status_code == 200:
        res = r.json()
        detail = f" det={res.get('detected_faces',0)} emb={res.get('embedding_created',False)}"
    elif r.status_code != 200:
        detail = r.text[:100]
    print(f"  [{status}] {img_path.name[:30]}{detail}")

# 5. 上传 3 张不同人的参考图 (Person_B)
print("\n--- Upload References (Person_B) ---")
for i, img_path in enumerate(images[6:9]):
    with open(img_path, "rb") as f:
        r = session.post(f"{BASE}/api/v1/references/upload", data={
            "project_id": project_id,
            "external_code": f"Person_B_{i+1}",
        }, files={"file": (img_path.name, f, "image/jpeg")})
    status = "OK" if r.status_code == 200 else f"ERR {r.status_code}"
    detail = ""
    if r.status_code == 200:
        res = r.json()
        detail = f" det={res.get('detected_faces',0)} emb={res.get('embedding_created',False)}"
    elif r.status_code != 200:
        detail = r.text[:100]
    print(f"  [{status}] {img_path.name[:30]}{detail}")

# 6. 上传 Probe
print("\n--- Upload Probe (same person Person_A) ---")
probe_path = images[4]
with open(probe_path, "rb") as f:
    r = session.post(f"{BASE}/api/v1/probes/upload", data={
        "project_id": project_id,
        "source_type": "folder",
        "async_mode": "false",
    }, files={"file": (probe_path.name, f, "image/jpeg")})
print(f"  status: {r.status_code}")
if r.status_code == 200:
    probe_data = r.json()
    probe_id = probe_data.get("probe_id")
    print(f"  probe_id: {probe_id}")
    print(f"  processing_status: {probe_data.get('status')}")
else:
    print(f"  error: {r.text[:300]}")
    probe_id = None

# 7. 查询 Probe 详情
if probe_id:
    time.sleep(2)
    r = session.get(f"{BASE}/api/v1/probes/{probe_id}")
    print(f"\n--- Probe Detail ---")
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        detail = r.json()
        print(f"  processing_status: {detail.get('processing_status')}")
        print(f"  faces_detected: {detail.get('faces_detected')}")
        print(f"  error_message: {detail.get('error_message')}")

# 8. 查询候选
if probe_id:
    r = session.get(f"{BASE}/api/v1/candidates", params={"probe_id": probe_id})
    print(f"\n--- Candidates (probe_id={probe_id}) ---")
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        candidates = r.json()
        print(f"  total candidates: {len(candidates)}")
        for c in candidates:
            rank = c.get("rank", "?")
            code = c.get("subject_code", "?")
            sim = c.get("similarity", 0)
            band = c.get("decision_band", "?")
            review = c.get("review_status", "?")
            print(f"    #{rank}: {code} sim={sim:.4f} band={band} review={review}")
    else:
        print(f"  error: {r.text[:300]}")

# 9. 测试复核操作
if probe_id and r.status_code == 200 and len(candidates) > 0:
    cid = candidates[0].get("id")
    print(f"\n--- Review Candidate {cid} (CONFIRM) ---")
    r = session.post(f"{BASE}/api/v1/candidates/{cid}/review", json={
        "action": "confirm",
        "reviewer": "e2e_test",
        "note": "E2E test confirmed",
    })
    print(f"  status: {r.status_code}")
    print(f"  body: {r.text[:200]}")

print("\n" + "=" * 50)
print("E2E test complete!")
