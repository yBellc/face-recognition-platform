"""P2 API contract smoke tests.

These tests deliberately avoid the model and database: they verify that the
deployment probe is public, protected APIs reject anonymous access, and the
critical governance/queue routes remain present in the OpenAPI contract.
Run with: ``python -m pytest -q`` from ``backend``.
"""

import httpx
import pytest

from app.main import app


@pytest.mark.anyio
async def test_health_is_public_and_has_model_version():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is True
    assert body["details"]["model_version"]["tag"]


@pytest.mark.anyio
async def test_protected_routes_reject_anonymous_access():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/monitoring/summary")
    assert response.status_code == 401


def test_governance_and_queue_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/api/v1/monitoring/queue" in paths
    assert "/api/v1/maintenance/retention" in paths
    assert "/api/v1/consents/{consent_id}/revoke" in paths
    assert "/api/v1/audit-logs" in paths
    assert "delete" in paths["/api/v1/probes/{probe_id}"]
