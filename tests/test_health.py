from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from product_studio.balance import BalanceConfig


def test_healthz_returns_ok_without_auth_while_other_routes_require_auth(
    monkeypatch: pytest.MonkeyPatch,
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    monkeypatch.setenv("ACCESS_KEY", "secret-access-key")
    client = make_client(None)

    health_resp = client.get("/healthz")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}

    root_resp = client.get("/")
    assert root_resp.status_code == 401

    post_health_resp = client.post("/healthz")
    assert post_health_resp.status_code == 401


def test_healthz_returns_ok_even_when_access_key_is_unset(
    monkeypatch: pytest.MonkeyPatch,
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    monkeypatch.delenv("ACCESS_KEY", raising=False)
    client = make_client(None)

    health_resp = client.get("/healthz")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}

    root_resp = client.get("/")
    assert root_resp.status_code == 503
