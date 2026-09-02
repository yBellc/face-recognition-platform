"""Dependency-light P2 contract check for environments without pytest."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.main import app  # noqa: E402


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://contract-test") as client:
        health = await client.get("/health")
        assert health.status_code == 200 and health.json()["healthy"] is True
        assert health.json()["details"]["model_version"]["tag"]
        protected = await client.get("/api/v1/monitoring/summary")
        assert protected.status_code == 401
    paths = app.openapi()["paths"]
    required = {
        "/api/v1/monitoring/queue",
        "/api/v1/maintenance/retention",
        "/api/v1/consents/{consent_id}/revoke",
        "/api/v1/audit-logs",
        "/api/v1/admin/users/{user_id}",
    }
    assert required.issubset(paths)
    assert "delete" in paths["/api/v1/probes/{probe_id}"]
    print("P2 contract checks passed")


if __name__ == "__main__":
    asyncio.run(main())
