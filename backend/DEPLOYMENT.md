# 生产部署与 P2 验收清单

## 1. 启动前置条件

- PostgreSQL 15+，启用 `vector` 与 `pgcrypto` 扩展。
- Redis 6+，作为 Celery broker/result backend。
- MinIO 或兼容 S3，对象桶至少包含 `probe-images`、`reference-images`。
- 安装 `backend/requirements.txt`，生产环境必须包含 `psycopg`、`redis`、`celery` 和 `minio`。

首次建库或升级时执行 `sql/schema.sql`。脚本包含账号、项目授权、同意记录、阈值配置和探针归档字段；重复执行安全。

## 2. 必填环境变量

```text
FACE_ENVIRONMENT=production
FACE_AUTH_SECRET=<随机且不提交到代码仓库的密钥>
FACE_ADMIN_PASSWORD=<首次管理员密码，部署后立即轮换>
FACE_DB_HOST=<postgres 主机>
FACE_DB_PORT=5432
FACE_DB_USER=<专用数据库账号>
FACE_DB_PASSWORD=<数据库密钥>
FACE_DB_NAME=face_recog
FACE_REDIS_URL=redis://<redis 主机>:6379/0
FACE_MINIO_ENDPOINT=<对象存储主机>:9000
FACE_MINIO_ACCESS_KEY=<对象存储账号>
FACE_MINIO_SECRET_KEY=<对象存储密钥>
FACE_CORS_ORIGINS=https://<正式前端域名>
```

应用在生产环境会拒绝默认密码、默认密钥、开发 CORS、SQLite 退化或缺少 PostgreSQL 驱动。

## 3. 进程与队列

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000
celery -A app.workers.celery_app.celery_app worker --loglevel=INFO --concurrency=2
```

队列任务启用晚确认、worker 丢失重投、软/硬超时和失败重试；探针处理在重试前会清理旧检测与候选，避免重复结果。

## 4. 上线验收

- `GET /health`：确认模型版本、数据库连接和服务时间。
- `GET /api/v1/monitoring/summary`：确认成功率、失败率、p50/p95/p99、队列数和模型版本。
- `GET /api/v1/monitoring/queue`：确认 Redis、worker 数量和数据库积压；`queue_ready` 必须为 `true`。
- `POST /api/v1/maintenance/retention`：默认只预览到期归档数据，审批后传 `dry_run=false` 执行并保留审计记录。
- `GET /api/v1/audit-logs`：管理员只读抽查登录、导出、删除、授权变更和保留期清理记录。
- `PATCH /api/v1/admin/users/{user_id}`：管理员变更账号启停、角色和项目授权；受保护请求会即时识别已停用账号。
- 运行 `python scripts/p2_contract_check.py`；有 pytest 环境时再运行 `python -m pytest -q`。

内部数据授权、1:1/1:N 评测、正式阈值与影子运行不在此清单内，必须等授权数据接入后单独验收。
