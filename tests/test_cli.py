from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def test_cli_main_uses_env_defaults_and_invokes_uvicorn_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from product_studio import cli

    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main([])

    assert captured["target"] == "product_studio.app:create_app"
    assert captured["kwargs"] == {
        "factory": True,
        "host": "0.0.0.0",
        "port": 9001,
        "reload": False,
    }


def test_cli_main_accepts_explicit_flags_over_env_and_loads_local_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from product_studio import cli

    (tmp_path / ".env").write_text("PORT=9123\nHOST=127.0.0.2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    captured: dict[str, Any] = {}

    def fake_run(target: str, **kwargs: Any) -> None:
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main(["--port", "8888", "--reload"])

    assert captured["target"] == "product_studio.app:create_app"
    assert captured["kwargs"] == {
        "factory": True,
        "host": "127.0.0.2",
        "port": 8888,
        "reload": True,
    }
