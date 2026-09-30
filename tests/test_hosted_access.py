import asyncio
import base64

from fastapi import Request
from fastapi.responses import JSONResponse

from web.app import private_hosted_access
from web.application.hosted_access import hosted_access_status


def _basic(username: str, password: str) -> str:
    value = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {value}"


def test_local_access_is_unchanged(monkeypatch):
    monkeypatch.delenv("EDGEIQ_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    assert hosted_access_status(None) == "allowed"


def test_hosted_access_fails_closed_without_password(monkeypatch):
    monkeypatch.setenv("EDGEIQ_DEPLOYMENT_MODE", "hosted")
    monkeypatch.delenv("EDGEIQ_HOSTED_ACCESS_PASSWORD", raising=False)
    assert hosted_access_status(None) == "unavailable"


def test_railway_cannot_be_switched_to_local_mode(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("EDGEIQ_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("EDGEIQ_HOSTED_ACCESS_PASSWORD", raising=False)
    assert hosted_access_status(None) == "unavailable"


def test_hosted_access_checks_basic_credentials(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("EDGEIQ_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("EDGEIQ_HOSTED_ACCESS_USER", "edgeiq")
    monkeypatch.setenv("EDGEIQ_HOSTED_ACCESS_PASSWORD", "long-private-password")
    assert hosted_access_status(None) == "credentials_required"
    assert hosted_access_status("Bearer token") == "credentials_required"
    assert hosted_access_status("Basic !!!") == "credentials_required"
    assert hosted_access_status(_basic("wrong", "long-private-password")) == "credentials_required"
    assert hosted_access_status(_basic("edgeiq", "wrong")) == "credentials_required"
    assert hosted_access_status(_basic("edgeiq", "long-private-password")) == "allowed"


def test_hosted_middleware_protects_api_but_allows_healthcheck(monkeypatch):
    monkeypatch.setenv("EDGEIQ_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("EDGEIQ_HOSTED_ACCESS_PASSWORD", "private-password")

    async def downstream(_request):
        return JSONResponse({"ok": True})

    def request(path: str, authorization: str | None = None) -> Request:
        headers = [(b"authorization", authorization.encode())] if authorization else []
        return Request({"type": "http", "method": "GET", "path": path, "headers": headers})

    blocked = asyncio.run(private_hosted_access(request("/api/version"), downstream))
    allowed = asyncio.run(private_hosted_access(request("/api/version", _basic("edgeiq", "private-password")), downstream))
    health = asyncio.run(private_hosted_access(request("/api/health"), downstream))
    assert blocked.status_code == 401
    assert blocked.headers["www-authenticate"].startswith("Basic")
    assert allowed.status_code == 200
    assert health.status_code == 200

    monkeypatch.delenv("EDGEIQ_HOSTED_ACCESS_PASSWORD")
    assert asyncio.run(private_hosted_access(request("/api/health"), downstream)).status_code == 503
