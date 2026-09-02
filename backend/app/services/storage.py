"""对象存储（MinIO / S3 兼容）封装"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import get_settings


class StorageClient:
    def __init__(self, settings=None):
        self.s = settings or get_settings()
        self.client: Optional[Minio] = None
        try:
            self.client = Minio(
                endpoint=self.s.minio_endpoint,
                access_key=self.s.minio_access_key,
                secret_key=self.s.minio_secret_key,
                secure=self.s.minio_secure,
            )
            for bucket in [self.s.minio_bucket_probe, self.s.minio_bucket_reference]:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
        except Exception as e:
            if self.s.environment.lower() == "production":
                raise RuntimeError(f"生产环境对象存储不可用，禁止退回本地文件系统: {e}") from e
            # 本地开发未启动 MinIO：退回到本地文件系统保存
            self.client = None
            self.fallback_dir = Path(__file__).resolve().parents[2] / "storage_fallback"
            self.fallback_dir.mkdir(exist_ok=True)
            (self.fallback_dir / self.s.minio_bucket_probe).mkdir(exist_ok=True)
            (self.fallback_dir / self.s.minio_bucket_reference).mkdir(exist_ok=True)

    def _safe_file_path(self, raw: str) -> Optional[Path]:
        """仅允许访问本系统 fallback 根目录下的文件，阻断 file:// 路径穿越。"""
        try:
            root = self.fallback_dir.resolve()
            path = Path(raw).resolve()
            if path == root or root not in path.parents:
                return None
            return path
        except Exception:
            return None

    def put_object(self, bucket: str, key: str, data: bytes,
                   content_type: str = "application/octet-stream") -> str:
        if self.client is not None:
            self.client.put_object(
                bucket, key, io.BytesIO(data), len(data),
                content_type=content_type,
            )
            return f"s3://{bucket}/{key}"
        p = self.fallback_dir / bucket / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return f"file://{p}"

    def put_file(self, bucket: str, key: str, local_path: str,
                 content_type: str = "application/octet-stream") -> str:
        with open(local_path, "rb") as f:
            return self.put_object(bucket, key, f.read(), content_type)

    def get_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        if self.client is not None:
            try:
                resp = self.client.get_object(bucket, key)
                return resp.read()
            except S3Error:
                return None
        p = self.fallback_dir / bucket / key
        return p.read_bytes() if p.exists() else None

    def get_local_path_or_download(self, bucket: str, key: str,
                                    dest_local_path: str) -> Optional[str]:
        """
        返回本地可读取的路径。
        - MinIO 模式：下载到 dest_local_path 并返回该路径
        - fallback 模式：直接返回原本地路径
        """
        if self.client is not None:
            try:
                self.client.fget_object(bucket, key, dest_local_path)
                return dest_local_path
            except S3Error:
                return None
        p = self.fallback_dir / bucket / key
        if not p.exists():
            return None
        Path(dest_local_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.abspath(str(p)) != os.path.abspath(dest_local_path):
            Path(dest_local_path).write_bytes(p.read_bytes())
        return dest_local_path

    def get_object(self, uri: str) -> Optional[bytes]:
        """
        从 URI 读取对象数据。
        支持: file:///path/to/file.jpg 或 s3://bucket/key
        """
        if uri.startswith("file://"):
            p = self._safe_file_path(uri[len("file://"):])
            if p is None:
                return None
            return p.read_bytes() if p.exists() else None
        elif uri.startswith("s3://"):
            rest = uri[len("s3://"):]
            bucket, key = rest.split("/", 1)
            return self.get_bytes(bucket, key)
        elif os.path.exists(uri):
            return Path(uri).read_bytes()
        return None

    def delete_object(self, uri: str) -> bool:
        """删除已登记的对象；仅接受本系统生成的 file:// 或 s3:// URI。"""
        try:
            if uri.startswith("file://"):
                path = self._safe_file_path(uri[len("file://"):])
                if path is None:
                    return False
                if path.exists() and path.is_file():
                    path.unlink()
                return True
            if uri.startswith("s3://") and self.client is not None:
                rest = uri[len("s3://"):]
                bucket, key = rest.split("/", 1)
                self.client.remove_object(bucket, key)
                return True
        except Exception:
            return False
        return False


_storage: Optional[StorageClient] = None


def get_storage() -> StorageClient:
    global _storage
    if _storage is None:
        _storage = StorageClient()
    return _storage
