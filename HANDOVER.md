# 驾驶舱人脸识别系统 — 技术交接文档

> **交接日期**: 2026-08-28  
> **文档版本**: v1.0  
> **项目目录**: `C:\Users\12408\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a90dde6b7b62ea1b5974b2e`

---

## 一、项目概述

本项目是一个驾驶舱人脸识别系统，用于在车辆图片中检测人脸并与已注册人员库进行 1:N 匹配，输出候选人员供人工复核。系统**不自动确认身份**，只给出候选和相似度。

### 4 页面架构

| 页面 | 路由 | 功能 |
|------|------|------|
| 人员库 | `/persons` | 新建匿名人员、上传参考照片、查看参考人脸、重新生成特征 |
| 图片识别 | `/recognize` | 上传车辆图片、显示人脸框、显示候选人员+相似度、标记"待复核" |
| 人工复核 | `/review` | 原图+人脸裁剪图+参考图对比、候选相似度、确认/排除/不确定 |
| 评测报告 | `/evaluation` | 数据集信息、模型版本、Top-1/Top-5、AUC/EER、FMR/FNMR、延迟统计 |

### 当前评测指标

| 指标 | 值 |
|------|-----|
| Top-1 Accuracy | 99.83% |
| Top-5 Accuracy | 99.83% |
| AUC | 1.0000 |
| EER | 0.0013 |
| FNMR@FMR=0.1% | 0.0013 |
| 假阳性 (False Accepts) | 0 |
| 假阴性 (False Rejects) | 4 |

---

## 二、技术栈

### 后端
- **Python 3.9+** + **FastAPI** (REST API)
- **SQLAlchemy 2.0** ORM
- **SQLite** (开发环境，生产应切换 PostgreSQL + pgvector)
- **InsightFace** buffalo_l (SCRFD 检测 + ArcFace R50 512维特征)
- **OpenCV** (图像处理)
- **MinIO** (对象存储，未启动时自动回退本地文件系统)

### 前端
- **React 18** + **Vite**
- **TypeScript**
- **Tailwind CSS**
- **React Router**

---

## 三、项目结构

```
项目根/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py              # pydantic-settings 配置，环境变量前缀 FACE_
│   │   ├── main.py                # FastAPI 主入口，所有路由定义 (~600行)
│   │   ├── schemas.py             # Pydantic 请求/响应 schema
│   │   ├── algorithm/
│   │   │   └── face_engine.py     # InsightFace 封装：检测+对齐+质量评估+特征提取+1:N检索 (~540行)
│   │   ├── db/
│   │   │   ├── models.py          # SQLAlchemy ORM 模型 (10张表)
│   │   │   └── session.py         # 数据库引擎+Session管理 (SQLite fallback)
│   │   ├── services/
│   │   │   ├── pipeline.py         # 核心处理管线：注册参考图 + 处理probe (~375行)
│   │   │   └── storage.py         # MinIO/本地文件存储封装
│   │   └── workers/
│   │       └── celery_app.py      # Celery worker (未使用，预留)
│   ├── data/
│   │   └── face_recog.db          # SQLite 数据库
│   ├── models/
│   │   └── models/
│   │       └── buffalo_l/         # 5个ONNX模型文件
│   │           ├── 1k3d68.onnx    # 3D关键点
│   │           ├── 2d106det.onnx   # 2D关键点
│   │           ├── det_10g.onnx    # 人脸检测 (SCRFD)
│   │           ├── genderage.onnx # 性别年龄
│   │           └── w600k_r50.onnx # ArcFace特征提取 (R50, 512-D)
│   ├── app.db                      # 旧SQLite（已废弃）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                # 4页面导航布局
│   │   ├── api.ts                 # Axios 客户端封装
│   │   └── pages/
│   │       ├── PersonLibraryPage.tsx   # 人员库页面
│   │       ├── ImageRecognitionPage.tsx # 图片识别页面
│   │       ├── ReviewPage.tsx          # 人工复核页面
│   │       └── EvaluationPage.tsx     # 评测报告页面
│   ├── package.json
│   └── vite.config.ts             # Vite配置，代理 /api → http://127.0.0.1:9091
├── scripts/
│   ├── init_dataset.py            # ★ 数据集初始化（正确分组版）
│   ├── write_eval_results.py      # ★ 写入评测结果到DB
│   ├── week1_algorithm_validation.py  # 全量评测脚本（600 DrivFace + 100 WIDER）
│   ├── e2e_test_v2.py             # ⚠ 旧初始化脚本（有bug，已被替代）
│   ├── download_datasets.py       # 数据集下载脚本
│   ├── download_insightface_model.py # InsightFace模型下载
│   └── ...                        # 其他测试脚本
├── data/
│   └── DrivFace/                  # DrivFace数据集 (606张JPG)
│       └── DrivFace/DrivImages/    # 20130529_XX_Driv_NNN_f.jpg
├── output/
│   └── week1/                     # 评测产物（CSV等）
└── HANDOVER.md                    # 本文档
```

---

## 四、数据库 Schema

### 10 张表结构

```
projects (1行)
  └── subjects (4行, Person_001~004)
        └── reference_images (12行, 每人3张)
              └── face_detections (reference类型)
                    └── embeddings (reference类型, owner_type='reference')
  └── probe_images (3行)
        └── face_detections (probe类型)
              └── embeddings (probe类型)
              └── match_candidates (3行, 候选匹配)
                    └── review_tasks (7行, 人工复核任务)

evaluation_runs (1行, run_id=1)
model_versions (0行, 预留)
audit_logs (15行, 操作日志)
```

### 关键表字段说明

**subjects**: `id, project_id, external_code (Person_001), display_name, authorization_status`

**reference_images**: `id, subject_id, object_uri (file://...), quality_score, sha256`

**probe_images**: `id, project_id, object_uri, processing_status (pending/processed/failed), processing_ms`

**face_detections**: `id, probe_image_id, reference_image_id, owner_type (probe/reference), bbox (JSON), landmarks (JSON), detector_score, quality_score, usable`

**embeddings**: `id, owner_type (probe/reference), owner_id (face_detection.id), model_version, vector (JSON数组, 512维), norm`

**match_candidates**: `id, probe_face_id, subject_id, similarity, rank, decision_band (high/medium/low), status (pending/confirmed/rejected/uncertain)`

**review_tasks**: `id, candidate_id, reviewer_id, decision, reason, reviewed_at`

**evaluation_runs**: `id, dataset_name, model_version, metrics_json (JSON), status, started_at, completed_at`

### metrics_json 当前内容

```json
{
  "AUC": 1.0,
  "EER": 0.0013,
  "FNMR_at_FMR001": 0.0013,
  "top1": 0.9983,
  "top5": 0.9983,
  "false_accepts": 0,
  "false_rejects": 4,
  "total_probes": 588,
  "detection_images": 100,
  "latency_p50": 2959,
  "latency_p95": 25705,
  "latency_p99": 25705
}
```

---

## 五、API 端点清单

所有 API 前缀: `/api/v1`，前端通过 Vite 代理转发到 `http://127.0.0.1:9091`。

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查，返回 `{healthy, latency, details:{model_version:{tag}}}` |
| GET | `/dashboard` | 仪表盘数据 |
| GET | `/projects` | 项目列表 |
| POST | `/projects` | 创建项目 |
| GET | `/subjects` | 人员列表 |
| POST | `/subjects` | 创建匿名人员 |
| GET | `/subjects/{id}` | 人员详情（含参考图） |
| POST | `/references` | 上传参考照片+自动提取特征 |
| POST | `/references/re-embed/{subject_id}` | 重新生成特征 |
| GET | `/probes/list` | probe列表（⚠ 路由在`/{probe_id}`之前） |
| POST | `/probes` | 上传probe图片 |
| GET | `/probes/{probe_id}` | probe详情 |
| GET | `/probes/{probe_id}/candidates` | 候选列表 |
| GET | `/candidates` | 全部候选列表 |
| PUT | `/candidates/{id}/decision` | 人工复核决策 |
| POST | `/evaluation/runs` | 创建评测记录 |
| GET | `/evaluation/runs` | 获取评测记录列表 |
| GET | `/images/probe/{probe_id}` | 获取probe原图 |
| GET | `/images/reference/{ref_id}` | 获取参考图 |

---

## 六、核心算法流程

### 6.1 参考图注册流程 (`pipeline.py: register_reference_image`)

```
上传图片bytes → SHA256去重 → 存储(MinIO/本地) → cv2解码
  → FaceEngine.detect_and_extract(检测+对齐+质量评估+特征提取)
  → 选质量最高的人脸 → 写入 reference_images + face_detections + embeddings
```

### 6.2 Probe处理流程 (`pipeline.py: process_probe`)

```
读取probe记录 → 下载图片 → cv2解码
  → FaceEngine.detect_and_extract(检测所有人脸)
  → 每个人脸写 face_detections + embeddings
  → build_gallery_from_db(从DB构建参考库)
  → 对每个usable人脸做 gallery.search() 1:N余弦相似度检索
  → 取每个subject最高相似度 → Top-K排序 → 决策带分类
  → 写入 match_candidates + review_tasks
  → 更新 probe.processing_status = "processed"
```

### 6.3 决策带阈值

配置在 `config.py`，可通过环境变量 `FACE_THRESHOLD_HIGH/MEDIUM/LOW` 覆盖：

| 带位 | 阈值 | 含义 |
|------|------|------|
| high | ≥0.75 | 高置信度，仍需人工确认 |
| medium | ≥0.60 | 中置信度，需人工复核 |
| low | ≥0.45 | 低置信度，仅供参考 |
| rejected | <0.45 | 不采纳 |

### 6.4 质量评估 (`face_engine.py: estimate_face_quality`)

综合评分 = 0.40×模糊度 + 0.15×亮度 + 0.20×尺寸 + 0.20×姿态 + 0.05×遮挡

- 模糊度: Laplacian方差，归一化到0-1 (除以300)
- 亮度: 偏离127.5的程度
- 尺寸: min(w,h)/120
- 姿态: yaw/pitch/roll 通过5点关键点粗略估计
- 遮挡: Canny边缘在人脸边缘区域的比例

---

## 七、如何运行

### 7.1 环境准备

```bash
# 后端依赖
cd backend
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 7.2 模型文件

InsightFace buffalo_l 模型已下载到 `backend/models/models/buffalo_l/`，包含5个ONNX文件。如需重新下载：

```bash
# 下载 buffalo_l.zip (约 298MB)
# 解压到 backend/models/models/buffalo_l/
```

### 7.3 启动后端

```bash
cd backend
# 端口 9091 (9090 可能被占用)
uvicorn app.main:app --host 0.0.0.0 --port 9091 --reload
```

后端启动时：
1. 检测 `psycopg` 是否安装 → 未安装则回退 SQLite
2. SQLite 模式下自动建表 (`Base.metadata.create_all`)
3. 加载 InsightFace buffalo_l 模型
4. MinIO 未启动时自动回退本地文件存储 (`backend/storage_fallback/`)

### 7.4 启动前端

```bash
cd frontend
npm run dev    # 默认端口 5173，可能被占用改用 3002
```

Vite 配置中 `/api` 代理到 `http://127.0.0.1:9091`。

### 7.5 初始化数据集

```bash
# 在项目根目录执行
python scripts/init_dataset.py
```

此脚本会：
1. 清空已有数据（subjects, reference_images, embeddings 等）
2. 创建项目
3. 解析 DrivFace 文件名 `20130529_XX_Driv_NNN_f.jpg`，按人员编号(01/02/03/04)分组
4. 为每个人员分配3张参考图（通过 API 上传，触发特征提取）
5. 创建2张 probe 图片并触发处理

### 7.6 写入评测结果

```bash
python scripts/write_eval_results.py
```

将 `output/week1/` 中的评测指标写入 `evaluation_runs` 表。

---

## 八、已踩过的坑 & 重要修复记录

### 8.1 ★ 人员库照片重复问题（已修复）

**现象**: 4个Person显示同一个人的脸  
**根因**: 旧脚本 `e2e_test_v2.py` 按文件名顺序取前8张JPG，但 DrivFace 前8张全是 Person 01 的照片  
**修复**: `scripts/init_dataset.py` 用正则 `_(\d+)_Driv_` 解析文件名，按人员编号分组分配  
**教训**: DrivFace 文件名格式为 `20130529_XX_Driv_NNN_f.jpg`，XX 是人员编号，不是序号

### 8.2 ndarray JSON 序列化错误（已修复）

**现象**: 向量写入DB时报 `TypeError: Object of type ndarray is not JSON serializable`  
**修复**: `pipeline.py` 中3处 `Embedding(vector=face.embedding)` 改为 `vector=face.embedding.astype(np.float32).tolist()`  
**位置**: `pipeline.py:171, 254, 369`

### 8.3 路由冲突（已修复）

**现象**: `GET /probes/list` 返回404或匹配到 `probe_id=list`  
**修复**: `main.py` 中将 `/probes/list` 路由定义移到 `/probes/{probe_id}` 之前  
**教训**: FastAPI 路径参数路由必须放在静态路由之后，否则 `{probe_id}` 会吞掉 `list`

### 8.4 Probe 处理时 session 隔离（已修复）

**现象**: probe 创建后 `process_probe` 读不到  
**修复**: `main.py:257-279` 在 probe 创建后立即 `session.commit()`，`process_probe` 在独立 session 中执行

### 8.5 SQLite 兼容（已修复）

**现象**: PostgreSQL 特有类型报错  
**修复**: `models.py` 中 `pgvector` 未安装时向量列退化为 `JSON` 类型；`session.py` 检测 `psycopg` 自动回退 SQLite；`BigInteger` → `Integer`

### 8.6 评测报告页面显示"暂无评测记录"（已修复）

**现象**: DB中有 run_id=1 但前端显示"暂无记录"  
**根因**: evaluation_runs 表 status 字段为 "running"、started_at/completed_at 为 NULL  
**修复**: 更新 status='success'、设置时间戳

### 8.7 ReviewPage 路径显示问题（已修复）

**现象**: 文件名显示完整路径或 `file://` 前缀  
**修复**: `ReviewPage.tsx:133-143` 改进 `fileName()` 函数，先去掉 `file://` 前缀，再按 `/` 和 `\` 分割取末尾

---

## 九、数据集说明

### DrivFace (UCI)

- **来源**: https://archive.ics.uci.edu/ml/machine-learning-databases/00378/DrivFace.zip
- **数量**: 606 张 JPG
- **人员**: 4 人 (编号 01/02/03/04)
- **文件名格式**: `20130529_XX_Driv_NNN_f.jpg`
  - XX = 人员编号 (01, 02, 03, 04)
  - NNN = 序号
  - 后缀: `_f` (front), `_lr` (low resolution), `_ll` (very low resolution)
- **分布**: Person 01=179张, Person 02=170张, Person 03=167张, Person 04=90张
- **路径**: `data/DrivFace/DrivFace/DrivImages/`

### WIDER FACE

- **来源**: http://shuoyang1213.me/WIDERFACE/
- **用途**: 评测检测能力（100张用于检测统计）
- **评测结果**: 检测到181个人脸，可用率 61.33%

### 数据集局限性

⚠️ DrivFace 仅4人，评测指标(AUC=1.0)可能过拟合，不具备生产参考价值。建议接入更大规模数据集。

---

## 十、后续待办（按优先级）

### P0 — 核心功能补全

1. **YOLO 车辆检测接入**
   - 目标: 解耦车辆框与人脸框，先检测车辆再在车辆区域内检测人脸
   - 方案: 集成 ultralytics YOLOv8，在 `pipeline.py` 中增加车辆检测步骤
   - 影响: `face_engine.py` 需新增 `VehicleDetector` 类，`pipeline.py` 的 `process_probe` 需先检测车辆

2. **误报案例详情展示**
   - 当前: 评测报告只显示假阳性/假阴性数量
   - 目标: 可点击查看具体误报案例图片

### P1 — 数据集扩展

3. **申请 DriveFace 数据集**
   - 受限数据集，需申请: https://visor-udg.github.io/DriveFace/
   - 包含视频帧，适合视频跟踪测试

4. **申请 iCarB-Face 数据集**
   - 申请地址: https://www.idiap.ch/en/dataset/icarb-face
   - 车载场景人脸数据，更贴合业务

### P2 — 视频与实时流

5. **ByteTrack 视频跟踪**
   - 在视频流中跟踪检测到的人脸，避免每帧重复识别
   - 影响: 新增 `video_tracker.py` 模块

6. **实时图片流接入**
   - 当前只支持单张上传，需支持文件夹批量导入或实时流

### P3 — 生产化

7. **PostgreSQL + pgvector 切换**
   - 当前 SQLite 不支持向量索引，1:N检索全量计算
   - 生产环境应切回 PostgreSQL + pgvector

8. **Celery 异步处理**
   - `workers/celery_app.py` 已预留，需接入 Redis 实现异步处理

9. **MinIO 对象存储**
   - 当前回退到本地文件系统，生产环境需启动 MinIO

---

## 十一、关键配置项

`backend/app/config.py` 中定义，环境变量前缀 `FACE_`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FACE_DB_HOST` | localhost | PostgreSQL主机 |
| `FACE_DB_PORT` | 5432 | PostgreSQL端口 |
| `FACE_DB_USER` | postgres | 用户名 |
| `FACE_DB_PASSWORD` | postgres | 密码 |
| `FACE_DB_NAME` | face_recog | 数据库名 |
| `FACE_REDIS_URL` | redis://localhost:6379/0 | Redis地址 |
| `FACE_MINIO_ENDPOINT` | localhost:9000 | MinIO地址 |
| `FACE_INSIGHTFACE_PROVIDERS` | ["CPUExecutionProvider"] | ONNX执行提供者 |
| `FACE_INSIGHTFACE_MODEL_ROOT` | "" (空=默认~/.insightface) | 模型根目录 |
| `FACE_TOP_K_CANDIDATES` | 5 | Top-K候选数 |
| `FACE_THRESHOLD_HIGH` | 0.75 | 高置信度阈值 |
| `FACE_THRESHOLD_MEDIUM` | 0.60 | 中置信度阈值 |
| `FACE_THRESHOLD_LOW` | 0.45 | 低置信度阈值 |
| `FACE_MIN_FACE_SIZE` | 40 | 最小人脸像素 |

### 启用 GPU

将 `FACE_INSIGHTFACE_PROVIDERS` 设置为 `["CUDAExecutionProvider", "CPUExecutionProvider"]`。

---

## 十二、前端 API 对接说明

前端使用 Axios 封装在 `frontend/src/api.ts`，baseURL 为空（走 Vite 代理）。

### 各页面 API 调用

| 页面 | API调用 |
|------|---------|
| 人员库 | `GET /subjects`, `POST /subjects`, `POST /references` (FormData), `POST /references/re-embed/{id}` |
| 图片识别 | `POST /probes` (FormData), `GET /probes/list`, `GET /probes/{id}/candidates` |
| 人工复核 | `GET /candidates`, `PUT /candidates/{id}/decision`, `GET /images/probe/{id}`, `GET /images/reference/{id}` |
| 评测报告 | `GET /evaluation/runs`, `GET /dashboard`, `GET /health` |

### 图片显示

后端提供图片端点返回 `StreamingResponse`：
- `GET /api/v1/images/probe/{probe_id}` — 返回probe原图
- `GET /api/v1/images/reference/{ref_id}` — 返回参考图

前端 `<img>` 标签直接使用这些URL。

---

## 十三、常用调试命令

```bash
# 查看数据库状态
python -c "import sqlite3; c=sqlite3.connect('backend/data/face_recog.db'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"

# 查看各表行数
python -c "
import sqlite3
c = sqlite3.connect('backend/data/face_recog.db')
for t in [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]:
    print(f'{t}: {c.execute(f\"SELECT COUNT(*) FROM {t}\").fetchone()[0]}')
"

# 测试API
curl http://127.0.0.1:9091/health
curl http://127.0.0.1:9091/api/v1/subjects
curl http://127.0.0.1:9091/api/v1/evaluation/runs

# 重新初始化数据集
python scripts/init_dataset.py

# 重新写入评测结果
python scripts/write_eval_results.py
```

---

## 十四、注意事项

1. **DrivFace 文件名有空格**: 文件名格式为 `20130529_01_Driv_001_f .jpg`（`f`后面有空格），解析时注意 `strip()`

2. **端口冲突**: 后端默认端口 8000，但常被占用，实际运行在 9091；前端默认 5173，实际可能运行在 3002。Vite 代理配置需对应后端端口

3. **SQLite 并发**: SQLite 不支持高并发写入，`check_same_thread=False` 只是绕过线程检查。生产环境必须切 PostgreSQL

4. **向量存储**: SQLite 模式下向量存储为 JSON 数组，1:N 检索是 Python 端全量计算（`gallery.search`），无向量索引。数据量大时需 pgvector

5. **不要使用 `scripts/e2e_test_v2.py`**: 此脚本有数据集分组bug，已被 `scripts/init_dataset.py` 替代

6. **模型路径**: `FaceEngine` 初始化时 `model_root` 指向 `backend/models`，实际模型在 `backend/models/models/buffalo_l/`。代码中拼接逻辑为 `Path(model_root) / "models" / self.model_name`

---

*文档结束。如有疑问请联系前任开发者。*
