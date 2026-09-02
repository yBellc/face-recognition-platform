"""端到端 API 测试脚本 v2: 修复 project 创建 + 错误捕获"""
import requests
import json
import time
import traceback
from pathlib import Path

BASE = "http://127.0.0.1:9090"
session = requests.Session()

# 1. Dashboard
print("--- Dashboard ---")
r = session.get(f"{BASE}/api/v1/dashboard")
print(f"  status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  model: {d.get('model_version')}")
    print(f"  thresholds: {json.dumps(d.get('thresholds', {}))}")

# 2. 创建项目 (修复: 检查 schema)
print("\n--- Create Project ---")
r = session.post(f"{BASE}/api/v1/projects", json={
    "name": "E2E Test",
    "description": "InsightFace E2E test",
    "project_type": "video_analysis",
})
print(f"  status: {r.status_code}")
if r.status_code == 200:
    proj = r.json()
    project_id = proj["id"]
    print(f"  project_id: {project_id}")
else:
    print(f"  body: {r.text[:300]}")
    # 尝试用已有项目
    r2 = session.get(f"{BASE}/api/v1/projects")
    if r2.status_code == 200 and len(r2.json()) > 0:
        project_id = r2.json()[0]["id"]
        print(f"  Using existing project: {project_id}")
    else:
        project_id = 1
        print("  Using fallback project_id=1")

# 3. 列出 DrivFace 图片
driv_dir = Path("data/DrivFace")
images = sorted(driv_dir.rglob("*.jpg"))
print(f"\nDrivFace: {len(images)} images total")

# 4. 上传参考图 Person_A
print("\n--- Upload References (Person_A) ---")
for i, img_path in enumerate(images[:3]):
    try:
        with open(img_path, "rb") as f:
            r = session.post(f"{BASE}/api/v1/references/upload", data={
                "project_id": str(project_id),
                "external_code": f"Person_A_{i+1}",
            }, files={"file": (img_path.name, f, "image/jpeg")}, timeout=60)
        if r.status_code == 200:
            res = r.json()
            print(f"  [OK] {img_path.name[:30]} det={res.get('detected_faces',0)} emb={res.get('embedding_created',False)}")
        else:
            print(f"  [{r.status_code}] {img_path.name[:30]} => {r.text[:200]}")
    except Exception as e:
        print(f"  [ERR] {img_path.name[:30]} => {e}")

# 5. 上传 Person_B 参考图
print("\n--- Upload References (Person_B) ---")
for i, img_path in enumerate(images[6:9]):
    try:
        with open(img_path, "rb") as f:
            r = session.post(f"{BASE}/api/v1/references/upload", data={
                "project_id": str(project_id),
                "external_code": f"Person_B_{i+1}",
            }, files={"file": (img_path.name, f, "image/jpeg")}, timeout=60)
        if r.status_code == 200:
            res = r.json()
            print(f"  [OK] {img_path.name[:30]} det={res.get('detected_faces',0)} emb={res.get('embedding_created',False)}")
        else:
            print(f"  [{r.status_code}] {img_path.name[:30]} => {r.text[:200]}")
    except Exception as e:
        print(f"  [ERR] {img_path.name[:30]} => {e}")

# 6. 上传 Probe
print("\n--- Upload Probe ---")
probe_path = images[4]
try:
    with open(probe_path, "rb") as f:
        r = session.post(f"{BASE}/api/v1/probes/upload", data={
            "project_id": str(project_id),
            "source_type": "folder",
            "async_mode": "false",
        }, files={"file": (probe_path.name, f, "image/jpeg")}, timeout=120)
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        probe_data = r.json()
        probe_id = probe_data.get("probe_id")
        print(f"  probe_id: {probe_id}")
        print(f"  processing_status: {probe_data.get('status')}")
    else:
        print(f"  body: {r.text[:300]}")
        probe_id = None
except Exception as e:
    print(f"  ERR: {e}")
    traceback.print_exc()
    probe_id = None

# 7. 查询 Probe 详情
if probe_id:
    time.sleep(3)
    r = session.get(f"{BASE}/api/v1/probes/{probe_id}", timeout=30)
    print(f"\n--- Probe {probe_id} Detail ---")
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        detail = r.json()
        print(f"  processing_status: {detail.get('processing_status')}")
        print(f"  faces_detected: {detail.get('faces_detected')}")
        print(f"  error_message: {detail.get('error_message')}")
        print(f"  candidates_count: {detail.get('candidates_count')}")

# 8. 查询候选
if probe_id:
    r = session.get(f"{BASE}/api/v1/candidates", params={"probe_id": probe_id}, timeout=30)
    print(f"\n--- Candidates ---")
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        candidates = r.json()
        print(f"  count: {len(candidates)}")
        for c in candidates:
            rank = c.get("rank", "?")
            code = c.get("subject_code", "?")
            sim = c.get("similarity", 0)
            band = c.get("decision_band", "?")
            review = c.get("review_status", "?")
            print(f"    #{rank}: {code} sim={sim:.4f} band={band} review={review}")
    else:
        print(f"  body: {r.text[:300]}")

# 9. Dashboard 更新
print("\n--- Dashboard (updated) ---")
r = session.get(f"{BASE}/api/v1/dashboard", timeout=10)
if r.status_code == 200:
    d = r.json()
    print(f"  band_counts: {json.dumps(d.get('band_counts', {}))}")
    ps = d.get("project_summary", {})
    print(f"  project_summary: {json.dumps(ps)}")

print("\nDone!")
