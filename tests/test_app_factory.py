from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_importing_app_module_has_no_filesystem_or_env_side_effects(
    tmp_path: Path,
) -> None:
    parent_dir = tmp_path / "workspace"
    project_dir = parent_dir / "repo"
    project_dir.mkdir(parents=True)
    (parent_dir / ".env").write_text("ACCESS_KEY=from-parent-env\n", encoding="utf-8")
    (project_dir / ".env").write_text("ACCESS_KEY=from-local-env\n", encoding="utf-8")

    env = os.environ.copy()
    env["ACCESS_KEY"] = "from-process-env"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import os, product_studio.app; print(os.environ.get('ACCESS_KEY', ''))"),
        ],
        cwd=project_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "from-process-env"
    assert not (project_dir / "outputs").exists()


def test_create_app_loads_local_env_without_overriding_existing_vars_or_reading_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_auth_headers: Callable[[str], dict[str, str]],
) -> None:
    from product_studio.app import create_app

    parent_dir = tmp_path / "parent"
    project_dir = parent_dir / "project"
    project_dir.mkdir(parents=True)
    (parent_dir / ".env").write_text(
        "PARENT_ONLY_KEY=should-not-load\n", encoding="utf-8"
    )
    (project_dir / ".env").write_text(
        "ACCESS_KEY=from-dotenv\nAPI_KEY=from-dotenv-api\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("ACCESS_KEY", "from-env")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("PARENT_ONLY_KEY", raising=False)

    app = create_app(output_dir=tmp_path / "out", load_env=True)
    client = TestClient(app)

    assert os.getenv("ACCESS_KEY") == "from-env"
    assert os.getenv("API_KEY") == "from-dotenv-api"
    assert os.getenv("PARENT_ONLY_KEY") is None

    resp = client.get("/api/config", headers=make_auth_headers("from-env"))
    assert resp.status_code == 200
    assert resp.json()["api_configured"] is True


def test_create_app_defaults_outputs_to_cwd_and_serves_packaged_static_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    from product_studio.app import create_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)

    app = create_app(load_env=False)
    client = TestClient(app)

    assert not (tmp_path / "outputs").exists()
    assert app.state.output_dir == tmp_path / "outputs"

    index_resp = client.get("/", headers=auth_headers)
    assert index_resp.status_code == 200

    static_resp = client.get("/static/ui_logic.js", headers=auth_headers)
    assert static_resp.status_code == 200
    assert "computeToolbarState" in static_resp.text


def test_routes_honor_fastapi_dependency_overrides_for_ledger_and_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    from product_studio.app import (
        create_app,
        get_balance_ledger,
        get_output_dir,
    )
    from product_studio.balance import BalanceConfig, BalanceLedger

    monkeypatch.setenv("API_KEY", "sk-override-test")

    default_dir = tmp_path / "default_out"
    override_dir = tmp_path / "override_out"
    override_dir.mkdir()
    (override_dir / "sample.png").write_bytes(b"png-bytes")

    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    custom_ledger = BalanceLedger(
        override_dir,
        config_loader=lambda: BalanceConfig(monthly_budget_usd=99.0),
        now_fn=lambda: now,
    )

    app = create_app(output_dir=default_dir, load_env=False)
    app.dependency_overrides[get_output_dir] = lambda: override_dir
    app.dependency_overrides[get_balance_ledger] = lambda: custom_ledger

    client = TestClient(app)

    assert not default_dir.exists()

    bal_resp = client.get("/api/balance", headers=auth_headers)
    assert bal_resp.status_code == 200
    assert bal_resp.json()["monthly_budget_usd"] == 99.0

    file_resp = client.get("/api/outputs/sample.png", headers=auth_headers)
    assert file_resp.status_code == 200
    assert file_resp.content == b"png-bytes"
