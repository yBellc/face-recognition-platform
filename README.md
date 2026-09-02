# 人脸识别系统 - Face Recognition System

基于 ChatGPT 分享方案构建的端到端人脸识别系统原型。

范围：公开/已授权数据、内网部署、相似候选标记、人工复核，不自动确认身份。

## 里程碑

| 阶段 | 周数 | 状态 | 交付物 |
|------|------|------|--------|
| P0 工程闭环 | 已完成 | ✅ | 建档、上传、检测、候选、人工复核、导出、归档 |
| P2 生产基线 | 本轮完成 | ✅ | 权限、上传校验、队列可靠性、留存清理、审计、监控 |
| P1 数据评测 | 待授权数据 | ⏳ | 内部 1:1/1:N、阈值校准、误报/漏报和无法判断统计 |
| P3 影子运行 | P1 通过后 | ⏳ | 小范围连续运行、抽样复核、上线验收 |

## 快速开始

```bash
# 1. 准备本地环境变量（不要提交 .env）
cp .env.example .env

# 2. 启动基础服务（PostgreSQL + pgvector + Redis + MinIO）
docker compose up -d

# 3. 安装后端依赖
cd backend && pip install -r requirements.txt

# 4. 初始化数据库（首次建库或升级时执行）
cd .. && psql -h localhost -U postgres -f sql/schema.sql

# 5. 运行算法验证脚本（仅公开/已授权数据）
python scripts/week1_algorithm_validation.py

# 6. 启动后端
cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. 启动前端
cd frontend && npm install && npm run dev
```

## 同事快速验收

仓库内的 `examples/demo_data` 是一套 57 张图片的匿名公开样例（8 个对象、单人图、未知人脸和多人合成图），可直接按 [examples/README.md](examples/README.md) 导入测试。接口级冒烟测试：

```bash
set FACE_DEMO_PASSWORD=<本地管理员密码>
python scripts/run_demo_smoke.py
```

该样例只证明流程能跑通，不代表内部场景准确率；内部人员照片必须放在授权的私有数据存储中。

## 技术栈

- 识别核心: InsightFace (SCRFD 检测 + ArcFace/Buffalo 特征)
- 服务端: Python FastAPI + Redis + Celery
- 数据库: PostgreSQL + pgvector
- 对象存储: MinIO (S3 兼容)
- 前端: React + Vite + TypeScript
- 部署: Docker Compose
