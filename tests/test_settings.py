from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from product_studio.app import create_app
from product_studio.balance import BalanceConfig


def test_config_exposes_factory_and_global_defaults_without_persisted_file(
    tmp_path: Path,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    resp = client.get("/api/config", headers=api_env)
    assert resp.status_code == 200
    data = resp.json()

    expected_factory = {
        "model": "gpt-image-2.5-sunburst",
        "quality": "medium",
        "concurrency": 2,
        "export_size": "1000x1000",
        "export_format": "png",
    }
    assert data["factory_defaults"] == expected_factory
    assert data["global_defaults"] == expected_factory
    assert not (tmp_path / ".settings").exists()


def test_put_settings_persists_global_defaults_across_app_instances(
    tmp_path: Path,
    api_env: dict[str, str],
) -> None:
    client_a = TestClient(create_app(output_dir=tmp_path, load_env=False))
    updated = {
        "model": "gpt-image-1.5",
        "quality": "high",
        "concurrency": 4,
        "export_size": "800x800",
        "export_format": "webp",
    }
    put_resp = client_a.put("/api/settings", headers=api_env, json=updated)
    assert put_resp.status_code == 200
    assert put_resp.json()["global_defaults"] == updated

    client_b = TestClient(create_app(output_dir=tmp_path, load_env=False))
    cfg_resp = client_b.get("/api/config", headers=api_env)
    assert cfg_resp.status_code == 200
    cfg = cfg_resp.json()
    assert cfg["global_defaults"] == updated
    assert cfg["factory_defaults"] == {
        "model": "gpt-image-2.5-sunburst",
        "quality": "medium",
        "concurrency": 2,
        "export_size": "1000x1000",
        "export_format": "png",
    }


def test_put_settings_rejects_invalid_or_partial_values_and_preserves_existing(
    tmp_path: Path,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    existing = {
        "model": "gpt-image-1.5",
        "quality": "high",
        "concurrency": 3,
        "export_size": "800x800",
        "export_format": "jpg",
    }
    setup_resp = client.put("/api/settings", headers=api_env, json=existing)
    assert setup_resp.status_code == 200

    bad_payloads = [
        {},
        {"quality": "low"},
        {
            "model": "unknown-model",
            "quality": "medium",
            "concurrency": 2,
            "export_size": "1000x1000",
            "export_format": "png",
        },
        {
            "model": "gpt-image-2.5-sunburst",
            "quality": "ultra",
            "concurrency": 2,
            "export_size": "1000x1000",
            "export_format": "png",
        },
        {
            "model": "gpt-image-2.5-sunburst",
            "quality": "medium",
            "concurrency": 8,
            "export_size": "1000x1000",
            "export_format": "png",
        },
        {
            "model": "gpt-image-2.5-sunburst",
            "quality": "medium",
            "concurrency": 2,
            "export_size": "500x500",
            "export_format": "png",
        },
        {
            "model": "gpt-image-2.5-sunburst",
            "quality": "medium",
            "concurrency": 2,
            "export_size": "1000x1000",
            "export_format": "bmp",
        },
    ]
    for payload in bad_payloads:
        resp = client.put("/api/settings", headers=api_env, json=payload)
        assert resp.status_code == 422, (
            f"Expected 422 for {payload}, got {resp.status_code}"
        )

    cfg_resp = client.get("/api/config", headers=api_env)
    assert cfg_resp.status_code == 200
    assert cfg_resp.json()["global_defaults"] == existing


def test_settings_store_fallback_is_immutable(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    from product_studio.settings import SettingsStore

    store_a = SettingsStore(tmp_path / "a")
    store_b = SettingsStore(tmp_path / "b")
    loaded_a = store_a.load()
    with pytest.raises(ValidationError):
        loaded_a.quality = "high"  # type: ignore[misc]
    assert store_b.load().quality == "medium"


def test_corrupt_or_partial_persisted_settings_falls_back_to_factory_defaults(
    tmp_path: Path,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    settings_dir = tmp_path / ".settings"
    settings_dir.mkdir()
    settings_file = settings_dir / "global_defaults.json"
    settings_file.write_text("{broken json", encoding="utf-8")

    client = make_client(None)
    resp = client.get("/api/config", headers=api_env)
    assert resp.status_code == 200
    assert resp.json()["global_defaults"] == resp.json()["factory_defaults"]

    settings_file.write_text(
        '{"model": "gpt-image-1.5", "quality": "invalid", "concurrency": 3}',
        encoding="utf-8",
    )
    resp2 = client.get("/api/config", headers=api_env)
    assert resp2.status_code == 200
    assert resp2.json()["global_defaults"] == {
        "model": "gpt-image-1.5",
        "quality": "medium",
        "concurrency": 3,
        "export_size": "1000x1000",
        "export_format": "png",
    }
