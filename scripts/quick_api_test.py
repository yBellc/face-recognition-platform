"""快速后端 API 测试"""
import requests, json
from pathlib import Path

BASE = "http://127.0.0.1:9090"
s = requests.Session()

# 1. Health
r = s.get(f"{BASE}/health", timeout=5)
print(f"[1] Health: {r.status_code} - {r.text[:200]}")

# 2. Dashboard
r = s.get(f"{BASE}/api/v1/dashboard", timeout=5)
print(f"[2] Dashboard: {r.status_code}")

# 3. Create Project (Form, not JSON)
r = s.post(f"{BASE}/api/v1/projects", data={
    "name": "E2E Test Project",
    "purpose": "Algorithm validation",
    "retention_days": "365",
}, timeout=5)
print(f"[3] Create Project: {r.status_code}")
if r.status_code == 200:
    proj = r.json()
    pid = proj["id"]
    print(f"    project_id={pid}")
else:
    print(f"    body: {r.text[:200]}")
    pid = 1

# 4. Upload reference image
img_path = sorted(Path("data/DrivFace").rglob("*.jpg"))[0]
print(f"\n[4] Upload reference: {img_path.name}")
with open(img_path, "rb") as f:
    r = s.post(f"{BASE}/api/v1/references/upload", data={
        "project_id": str(pid),
        "external_code": "Person_001",
    }, files={"file": (img_path.name, f, "image/jpeg")}, timeout=60)
print(f"    status: {r.status_code}")
if r.status_code == 200:
    res = r.json()
    print(f"    det={res.get('detected_faces',0)} emb={res.get('embedding_created',False)} q={res.get('quality_score','N/A')}")
else:
    print(f"    error: {r.text[:300]}")

# 5. Upload probe
img_path2 = sorted(Path("data/DrivFace").rglob("*.jpg"))[3]
print(f"\n[5] Upload probe: {img_path2.name}")
with open(img_path2, "rb") as f:
    r = s.post(f"{BASE}/api/v1/probes/upload", data={
        "project_id": str(pid),
        "source_type": "folder",
        "async_mode": "false",
    }, files={"file": (img_path2.name, f, "image/jpeg")}, timeout=120)
print(f"    status: {r.status_code}")
if r.status_code == 200:
    probe = r.json()
    print(f"    probe_id={probe.get('probe_id')} status={probe.get('status')}")
else:
    print(f"    error: {r.text[:300]}")

# 6. List candidates
if r.status_code == 200:
    pid_val = probe.get("probe_id")
    r = s.get(f"{BASE}/api/v1/candidates", params={"probe_id": pid_val}, timeout=10)
    print(f"\n[6] Candidates: {r.status_code}")
    if r.status_code == 200:
        cands = r.json()
        print(f"    count={len(cands)}")
        for c in cands:
            print(f"    #{c.get('rank')}: {c.get('subject_code')} sim={c.get('similarity',0):.4f} band={c.get('decision_band')}")
    else:
        print(f"    error: {r.text[:300]}")

print("\nDone!")
