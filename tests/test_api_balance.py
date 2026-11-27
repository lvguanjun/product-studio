from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from product_studio.balance import BalanceConfig


def _make_png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeUpstreamResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_config_and_balance_endpoints_expose_balance_snapshot(
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    config_resp = client.get("/api/config", headers=api_env)
    assert config_resp.status_code == 200
    config_data = config_resp.json()
    assert "balance" in config_data
    assert config_data["balance"]["monthly_budget_usd"] == 25.0
    assert config_data["balance"]["remaining_usd"] == 25.0
    assert config_data["balance"]["status"] == "ok"

    bal_resp = client.get("/api/balance", headers=api_env)
    assert bal_resp.status_code == 200
    assert bal_resp.json()["billing_month"] == "2026-11"


def test_generate_blocks_with_402_when_below_threshold_while_history_and_download_work(
    tmp_path: Path,
    fixed_now: datetime,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(
        BalanceConfig(
            monthly_budget_usd=25.0,
            warn_threshold_usd=5.0,
            disable_threshold_usd=1.0,
            used_offset_usd=24.2,
        )
    )
    sample_img = _make_png_bytes((255, 255, 255))
    (tmp_path / "abc123_demo_white.png").write_bytes(sample_img)
    (tmp_path / "abc123.json").write_text(
        json.dumps(
            {
                "id": "abc123",
                "filename": "abc123_demo_white.png",
                "orig_name": "demo.png",
                "url": "/api/outputs/abc123_demo_white.png",
                "mime": "image/png",
                "size_kb": 1.2,
                "output_size": "1000x1000",
                "model": "gpt-image-2.5-sunburst",
                "quality": "medium",
                "elapsed": 1.5,
                "usage": {
                    "input_tokens": 1067,
                    "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
                    "output_tokens": 439,
                    "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
                },
                "created_at": int(fixed_now.timestamp()) - 3600,
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "product_studio.app.httpx.AsyncClient.post", new_callable=AsyncMock
    ) as mock_post:
        gen_resp = client.post(
            "/api/generate",
            headers=api_env,
            files={"file": ("item.png", _make_png_bytes(), "image/png")},
            data={"prompt": "white background"},
        )
        assert gen_resp.status_code == 402
        body = gen_resp.json()
        assert body["code"] == "BALANCE_BELOW_THRESHOLD"
        assert body["balance"]["disabled"] is True
        mock_post.assert_not_awaited()

    hist_resp = client.get("/api/history", headers=api_env)
    assert hist_resp.status_code == 200
    items = hist_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["cost_usd"] == pytest.approx(0.021289, abs=1e-6)

    file_resp = client.get("/api/outputs/abc123_demo_white.png", headers=api_env)
    assert file_resp.status_code == 200

    zip_resp = client.post(
        "/api/download-zip",
        headers=api_env,
        json={"filenames": ["abc123_demo_white.png"]},
    )
    assert zip_resp.status_code == 200


def test_generate_charges_ledger_and_returns_cost_and_updated_balance(
    tmp_path: Path,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    fake_png_b64 = base64.b64encode(_make_png_bytes((255, 255, 255))).decode("ascii")
    fake_resp = _FakeUpstreamResponse(
        {
            "data": [{"b64_json": fake_png_b64}],
            "usage": {
                "input_tokens": 1067,
                "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
                "output_tokens": 439,
                "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
                "total_tokens": 1506,
            },
        }
    )

    with patch(
        "product_studio.app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=fake_resp,
    ):
        resp = client.post(
            "/api/generate",
            headers=api_env,
            files={"file": ("shoe.png", _make_png_bytes(), "image/png")},
            data={"prompt": "white background", "model": "gpt-image-2.5-sunburst"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["cost_usd"] == pytest.approx(0.021289, abs=1e-6)
    assert payload["cost_source"] == "usage"
    assert payload["balance"]["used_usd"] == pytest.approx(0.021289, abs=1e-6)
    assert payload["balance"]["remaining_usd"] == pytest.approx(
        25.0 - 0.021289, abs=1e-6
    )

    saved_meta = json.loads(
        (tmp_path / f"{payload['id']}.json").read_text(encoding="utf-8")
    )
    assert saved_meta["cost_usd"] == pytest.approx(0.021289, abs=1e-6)
    assert saved_meta["key_fingerprint"]
