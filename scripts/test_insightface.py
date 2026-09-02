"""测试 InsightFace 真模型加载"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.algorithm.face_engine import FaceEngine

model_root = str(Path(__file__).resolve().parent.parent / "backend" / "models")
print(f"Model root: {model_root}")
buffalo_dir = Path(model_root) / "models" / "buffalo_l"
print(f"Model dir exists: {buffalo_dir.exists()}")
if buffalo_dir.exists():
    for f in sorted(buffalo_dir.glob("*.onnx")):
        print(f"  {f.name} ({f.stat().st_size / 1024 / 1024:.1f}MB)")

print("\n--- Initializing FaceEngine ---")
engine = FaceEngine(model_root=model_root)
print(f"Fallback mode: {engine._fallback}")

if not engine._fallback:
    print("\n✅ InsightFace loaded successfully!")
    print(f"Analysis type: {type(engine._analysis).__name__}")
    
    import cv2
    import time
    
    driv_dir = Path(__file__).resolve().parent.parent / "data" / "DrivFace"
    imgs = list(driv_dir.rglob("*.jpg"))
    print(f"\nDrivFace images found: {len(imgs)}")
    
    if imgs:
        img = cv2.imread(str(imgs[0]))
        print(f"Test image: {imgs[0].name} ({img.shape})")
        t0 = time.time()
        faces = engine.detect_and_extract(img, min_face_size=40, compute_embedding=True)
        dt = (time.time() - t0) * 1000
        print(f"Detection: {len(faces)} faces in {dt:.0f}ms")
        for i, f in enumerate(faces):
            emb_info = f"shape={f.embedding.shape}" if f.embedding is not None else "None"
            print(f"  Face#{i}: bbox=({f.bbox.x},{f.bbox.y},{f.bbox.w},{f.bbox.h}) "
                  f"Q={f.quality_score:.3f} det={f.detector_score:.3f} "
                  f"usable={f.usable} {emb_info}")
        
        # 测试 1:N 检索
        from app.algorithm.face_engine import ReferenceGallery
        import numpy as np
        
        gallery = ReferenceGallery(threshold_high=0.75, threshold_medium=0.60, threshold_low=0.45)
        # 注册前3张图的特征
        for img_path in imgs[:3]:
            img = cv2.imread(str(img_path))
            faces = engine.detect_and_extract(img, compute_embedding=True)
            for face in faces:
                if face.usable and face.embedding is not None:
                    gallery.add_embedding(face.embedding, subject_id=img_path.stem[:12])
        
        print(f"\nGallery size: {len(gallery._embeddings)} embeddings")
        
        # 测试 probe
        if len(imgs) > 5:
            probe = cv2.imread(str(imgs[5]))
            probe_faces = engine.detect_and_extract(probe, compute_embedding=True)
            for pf in probe_faces:
                if pf.usable and pf.embedding is not None:
                    results = gallery.search(pf.embedding, top_k=3)
                    print(f"\nProbe {imgs[5].name}:")
                    for r in results:
                        print(f"  #{r.rank}: {r.subject_id} sim={r.similarity:.3f} band={r.decision_band}")
else:
    print("\n❌ Still in fallback mode!")
    print(f"Error message check the log above.")
