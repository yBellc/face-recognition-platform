"""Init dataset — correctly map DrivFace images per person."""
import re, requests
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data" / "DrivFace" / "DrivFace" / "DrivImages"
BASE = "http://127.0.0.1:9091"
s = requests.Session()

jpgs = sorted(DATA_ROOT.glob("*.jpg"))
by_person = defaultdict(list)
for p in jpgs:
    m = re.search(r"_(\d+)_Driv_", p.name)
    if m:
        by_person[int(m.group(1))].append(p)

print("DrivFace persons:", {k: len(v) for k, v in by_person.items()})

r = s.post(f"{BASE}/api/v1/projects", data={"name": "DrivFace 驾驶员识别", "retention_days": "365"})
proj_id = r.json()["id"]
print(f"Project: {proj_id}")

person_map = {1: "Person_001", 2: "Person_002", 3: "Person_003", 4: "Person_004"}
subject_ids = {}
for pn, code in person_map.items():
    r = s.post(f"{BASE}/api/v1/subjects", json={"project_id": proj_id, "external_code": code})
    subject_ids[pn] = r.json()["id"]
    print(f"{code}: subject_id={subject_ids[pn]}")

for pn in sorted(by_person.keys()):
    code = person_map[pn]
    ref_files = by_person[pn][:3]
    print(f"\nUploading 3 refs for {code} from person {pn:02d}:")
    for img_path in ref_files:
        with open(img_path, "rb") as f:
            r = s.post(f"{BASE}/api/v1/references/upload",
                data={"project_id": str(proj_id), "external_code": code},
                files={"file": (img_path.name, f, "image/jpeg")}, timeout=60)
        status = "OK" if r.status_code == 200 else f"ERR {r.status_code}"
        print(f"  {img_path.name}: {status}")

# Test: Person 01 image #5
print("\n--- Test: Person 01 image ---")
probe_img = by_person[1][4]
with open(probe_img, "rb") as f:
    r = s.post(f"{BASE}/api/v1/probes/upload",
        data={"project_id": str(proj_id), "source_type": "folder", "async_mode": "false"},
        files={"file": (probe_img.name, f, "image/jpeg")}, timeout=120)
if r.status_code == 200:
    pid = r.json()["probe_id"]
    r2 = s.get(f"{BASE}/api/v1/candidates", params={"probe_id": pid})
    for c in r2.json():
        mark = " <<< CORRECT" if c.get("subject_code") == "Person_001" else ""
        print(f"  #{c['rank']}: {c['subject_code']} sim={c['similarity']:.4f}{mark}")

# Test: Person 03 image #5
print("\n--- Test: Person 03 image ---")
probe_img2 = by_person[3][4]
with open(probe_img2, "rb") as f:
    r = s.post(f"{BASE}/api/v1/probes/upload",
        data={"project_id": str(proj_id), "source_type": "folder", "async_mode": "false"},
        files={"file": (probe_img2.name, f, "image/jpeg")}, timeout=120)
if r.status_code == 200:
    pid2 = r.json()["probe_id"]
    r2 = s.get(f"{BASE}/api/v1/candidates", params={"probe_id": pid2})
    for c in r2.json():
        mark = " <<< CORRECT" if c.get("subject_code") == "Person_003" else ""
        print(f"  #{c['rank']}: {c['subject_code']} sim={c['similarity']:.4f}{mark}")

print("\nDone! Refresh browser to see updated persons.")
