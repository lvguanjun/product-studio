from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from product_studio.app import create_app
from product_studio.balance import BalanceConfig, BalanceLedger


def _build_basic_auth_headers(access_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{access_key}:{access_key}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def make_auth_headers() -> Callable[[str], dict[str, str]]:
    return _build_basic_auth_headers


@pytest.fixture
def auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    make_auth_headers: Callable[[str], dict[str, str]],
) -> dict[str, str]:
    monkeypatch.setenv("ACCESS_KEY", "test-access")
    return make_auth_headers("test-access")


@pytest.fixture
def api_env(
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> dict[str, str]:
    monkeypatch.setenv("API_KEY", "sk-proj-test-balance-key")
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "25")
    monkeypatch.setenv("BALANCE_WARN_THRESHOLD_USD", "5")
    monkeypatch.setenv("BALANCE_DISABLE_THRESHOLD_USD", "1")
    monkeypatch.setenv("BILLING_TIMEZONE", "UTC")
    monkeypatch.delenv("BALANCE_USED_OFFSET_USD", raising=False)
    monkeypatch.delenv("BALANCE_USED_OFFSET_MONTH", raising=False)
    return auth_headers


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def make_client(
    tmp_path: Path,
    fixed_now: datetime,
) -> Callable[[BalanceConfig | None], TestClient]:
    def _factory(config: BalanceConfig | None = None) -> TestClient:
        ledger = (
            BalanceLedger(tmp_path, now_fn=lambda: fixed_now)
            if config is None
            else BalanceLedger(
                tmp_path,
                config_loader=lambda: config,
                now_fn=lambda: fixed_now,
            )
        )
        app = create_app(output_dir=tmp_path, ledger=ledger, load_env=False)
        return TestClient(app)

    return _factory
