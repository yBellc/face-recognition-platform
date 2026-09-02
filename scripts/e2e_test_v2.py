"""完整端到端 API 测试 - 4 页面架构"""
import requests
from pathlib import Path

# 从项目根目录解析数据路径
ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data" / "DrivFace" / "DrivFace" / "DrivImages"

BASE = "http://127.0.0.1:9091"
s = requests.Session()

# 1. Health
r = s.get(f"{BASE}/health")
print(f"[1] Health: {r.status_code}")

# 2. Create Project
r = s.post(f"{BASE}/api/v1/projects", data={"name": "DrivFace Test", "retention_days": "365"})
proj_id = r.json()["id"]
print(f"[2] Project created: id={proj_id}")

# 3. Create subjects for 4 people, track IDs
subject_ids = {}
for code in ["Person_001", "Person_002", "Person_003", "Person_004"]:
    r = s.post(f"{BASE}/api/v1/subjects", json={"project_id": proj_id, "external_code": code})
    sid = r.json()['id']
    subject_ids[code] = sid
    print(f"  Subject {code}: id={sid}")

# 4. Upload reference images (2 per person)
jpgs = sorted(DATA_ROOT.glob("*.jpg"))
print(f"\n[4] Found {len(jpgs)} jpg files in {DATA_ROOT}")
ref_jpgs = jpgs[:8]
print(f"    Using first {len(ref_jpgs)} as references")
for i, img_path in enumerate(ref_jpgs):
    code = f"Person_{(i // 2) + 1:03d}"
    with open(img_path, "rb") as f:
        r = s.post(
            f"{BASE}/api/v1/references/upload",
            data={"project_id": str(proj_id), "external_code": code},
            files={"file": (img_path.name, f, "image/jpeg")},
            timeout=60,
        )
    if r.status_code == 200:
        res = r.json()
        print(f"  #{i} {code}: quality={res.get('quality_score', 'N/A')} ref_id={res.get('reference_image_id', 'N/A')}")
    else:
        print(f"  #{i} {code}: ERROR {r.status_code} - {r.text[:200]}")

# 5. Upload probe and recognize
probe_img = jpgs[10]
print(f"\n[5] Uploading probe: {probe_img.name}")
with open(probe_img, "rb") as f:
    r = s.post(
        f"{BASE}/api/v1/probes/upload",
        data={"project_id": str(proj_id), "source_type": "folder", "async_mode": "false"},
        files={"file": (probe_img.name, f, "image/jpeg")},
        timeout=120,
    )
probe_data = None
if r.status_code == 200:
    probe_data = r.json()
    pid_val = probe_data.get("probe_id")
    status = probe_data.get('status')
    print(f"  probe_id={pid_val} status={status}")

    # Get candidates
    r = s.get(f"{BASE}/api/v1/candidates", params={"probe_id": pid_val})
    cands_saved = []
    if r.status_code == 200:
        cands_saved = r.json()
        print(f"  Candidates ({len(cands_saved)}):")
        for c in cands_saved:
            print(f"    #{c.get('rank')}: {c.get('subject_code')} sim={c.get('similarity', 0):.4f} band={c.get('decision_band')}")
    else:
        print(f"  Candidates error: {r.status_code}")
else:
    print(f"  Probe error: {r.status_code} - {r.text[:300]}")
    cands_saved = []

# 6. Test new endpoints
print("\n[6] Testing new endpoints...")

# 6a. Subject references (use actual subject ID)
first_sid = subject_ids.get("Person_001")
if first_sid:
    r = s.get(f"{BASE}/api/v1/subjects/{first_sid}/references")
    print(f"  Subject {first_sid} references: {r.status_code} - {len(r.json())} items")

# 6b. Probe list
r = s.get(f"{BASE}/api/v1/probes/list", params={"project_id": proj_id})
print(f"  Probe list: {r.status_code} - {len(r.json())} items")

# 6c. Evaluation runs
r = s.get(f"{BASE}/api/v1/evaluation/runs")
print(f"  Evaluation runs: {r.status_code} - {len(r.json())} items")

# 6d. Dashboard
r = s.get(f"{BASE}/api/v1/dashboard")
if r.status_code == 200:
    d = r.json()
    print(f"  Dashboard: {r.status_code} - probes_today={d.get('probe_image_count_today', 'N/A')}")
else:
    print(f"  Dashboard: {r.status_code}")

# 7. Review candidate (if any)
if cands_saved and len(cands_saved) > 0:
    c0 = cands_saved[0]
    print(f"\n[7] Reviewing candidate #{c0.get('id')}...")
    r = s.post(f"{BASE}/api/v1/candidates/{c0['id']}/review", json={"decision": "confirm"})
    print(f"  Review: {r.status_code}")
else:
    print("\n[7] No candidates to review")

print("\nDone!")