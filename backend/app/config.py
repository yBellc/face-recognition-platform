"""
人脸识别系统 - 配置管理
使用 pydantic-settings，支持环境变量覆盖
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # --- 运行环境 ---
    environment: str = "development"  # development / staging / production
    cors_origins: str = "http://127.0.0.1:3002,http://localhost:3002"

    # --- 数据库 ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "face_recog"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"

    # --- MinIO ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_probe: str = "probe-images"
    minio_bucket_reference: str = "reference-images"
    minio_secure: bool = False

    # --- 算法 ---
    default_model_version: str = "insightface-buffalo-l-v1"
    insightface_providers: list = ["CPUExecutionProvider"]  # CUDAExecutionProvider 放首位启用GPU
    insightface_model_root: str = ""  # 本地模型目录，留空用默认 ~/.insightface
    top_k_candidates: int = 5
    threshold_high: float = 0.75
    threshold_medium: float = 0.60
    threshold_low: float = 0.45
    min_face_size: int = 40  # 质量过滤：最小人脸像素尺寸

    # --- 上传与认证防护 ---
    max_upload_mb: int = 10
    auth_rate_limit_attempts: int = 8
    auth_rate_limit_window_seconds: int = 300
    celery_task_time_limit_seconds: int = 180
    celery_task_soft_time_limit_seconds: int = 150

    # --- 系统 ---
    project_name: str = "Face Recognition System"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_prefix = "FACE_"
        env_file = ".env"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
