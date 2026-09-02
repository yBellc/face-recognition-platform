"""Debug: check DB directly and test pipeline"""
import sys, traceback
sys.path.insert(0, "backend")

from app.db.session import new_engine, _SQLITE_PATH
from sqlalchemy import text

engine = new_engine()

# 检查表结构
with engine.connect() as conn:
    tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    print("Tables:", [t[0] for t in tables])
    
    if "embeddings" in [t[0] for t in tables]:
        cols = conn.execute(text("PRAGMA table_info(embeddings)")).fetchall()
        for c in cols:
            print(f"  {c[1]}: {c[2]} notnull={c[3]}")
    
    if "projects" in [t[0] for t in tables]:
        cols = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        for c in cols:
            print(f"  {c[1]}: {c[2]} notnull={c[3]}")

# 直接测试 pipeline
print("\n=== Direct pipeline test ===")
from app.db.session import session_scope
from app.services.pipeline import register_reference_image
from pathlib import Path

img_path = sorted(Path("data/DrivFace").rglob("*.jpg"))[0]
print(f"Testing with: {img_path.name}")

with open(img_path, "rb") as f:
    img_bytes = f.read()

try:
    with session_scope() as s:
        from app.db.models import Project
        p = s.get(Project, 1)
        if p is None:
            p = Project(name="E2E Test", retention_days=365)
            s.add(p)
            s.commit()
            s.refresh(p)
            print(f"Created project: {p.id}")
        else:
            print(f"Found project: {p.id} {p.name}")
        
        result = register_reference_image(
            session=s, project_id=1,
            external_code="Test_Person_1",
            image_bytes=img_bytes, file_ext="jpg",
        )
        print(f"Result: {result}")
except Exception as e:
    traceback.print_exc()
