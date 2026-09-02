"""
Celery Worker —— 异步任务队列
对应方案第六部分：任务队列（接收/检测/特征/检索/复核）

第一版用最基础的 process_probe 任务，后续可拆分出：
  - task_ingest_probe
  - task_detect_faces
  - task_extract_embeddings
  - task_search_candidates
"""
from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from app.config import get_settings
from app.db.session import session_scope
from app.services.pipeline import get_face_engine, process_probe

settings = get_settings()

celery_app = Celery(
    "face_recog_tasks",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=max(30, int(settings.celery_task_time_limit_seconds)),
    task_soft_time_limit=max(20, int(settings.celery_task_soft_time_limit_seconds)),
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": max(300, int(settings.celery_task_time_limit_seconds) * 3)},
)


@worker_process_init.connect
def warmup_engine(**_kwargs):
    """每个 worker 进程启动时预热一次人脸引擎，避免首次任务卡顿"""
    try:
        get_face_engine()
    except Exception:
        pass


@celery_app.task(name="tasks.process_probe", bind=True, max_retries=3,
                 default_retry_delay=5)
def task_process_probe(self, probe_id: int) -> dict:
    try:
        with session_scope() as sess:
            result = process_probe(sess, probe_id)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error") or "probe 处理失败")
            return result
    except Exception as exc:
        raise self.retry(exc=exc)


def enqueue_process_probe(probe_id: int) -> str:
    r = task_process_probe.delay(probe_id)
    return r.id
