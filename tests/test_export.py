from __future__ import annotations

import base64
import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote

from fastapi.testclient import TestClient
from PIL import Image

from product_studio.balance import BalanceConfig


def _make_png_bytes(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeUpstreamResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_product_image_download_strips_random_id_prefix_in_content_disposition(
    tmp_path: Path,
    make_client: Callable[[BalanceConfig | None], TestClient],
    auth_headers: dict[str, str],
) -> None:
    stored_name = "a1b2c3d4e5f6_SKU_1001_white.png"
    (tmp_path / stored_name).write_bytes(b"fake-png-bytes")

    client = make_client(None)
    response = client.get(f"/api/outputs/{stored_name}", headers=auth_headers)

    assert response.status_code == 200
    disposition = unquote(response.headers.get("content-disposition", ""))
    assert "SKU_1001_white.png" in disposition
    assert "a1b2c3d4e5f6" not in disposition


def test_product_image_download_preserves_plain_names_and_handles_cjk(
    tmp_path: Path,
    make_client: Callable[[BalanceConfig | None], TestClient],
    auth_headers: dict[str, str],
) -> None:
    plain_name = "sample.png"
    cjk_stored = "0123456789ab_粘贴图片_white.png"
    (tmp_path / plain_name).write_bytes(b"plain")
    (tmp_path / cjk_stored).write_bytes(b"cjk")

    client = make_client(None)

    plain_resp = client.get(f"/api/outputs/{plain_name}", headers=auth_headers)
    assert plain_resp.status_code == 200
    assert "sample.png" in unquote(plain_resp.headers.get("content-disposition", ""))

    cjk_resp = client.get(f"/api/outputs/{cjk_stored}", headers=auth_headers)
    assert cjk_resp.status_code == 200
    cjk_disposition = unquote(cjk_resp.headers.get("content-disposition", ""))
    assert "粘贴图片_white.png" in cjk_disposition
    assert "0123456789ab" not in cjk_disposition


def test_download_zip_uses_clean_deduplicated_export_filenames(
    tmp_path: Path,
    make_client: Callable[[BalanceConfig | None], TestClient],
    auth_headers: dict[str, str],
) -> None:
    files = {
        "aaaaaaaaaaaa_mug_white.png": b"first",
        "bbbbbbbbbbbb_MUG_white.png": b"second",
        "cccccccccccc_mug_white.png": b"third",
        "dddddddddddd_cup_white.jpg": b"fourth",
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)

    client = make_client(None)
    response = client.post(
        "/api/download-zip",
        json={"filenames": list(files.keys())},
        headers=auth_headers,
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content), "r") as archive:
        names = archive.namelist()
        assert names == [
            "mug_white.png",
            "MUG_white_2.png",
            "mug_white_3.png",
            "cup_white.jpg",
        ]
        assert archive.read("mug_white.png") == b"first"
        assert archive.read("MUG_white_2.png") == b"second"
        assert archive.read("mug_white_3.png") == b"third"
        assert archive.read("cup_white.jpg") == b"fourth"


def test_history_backfills_export_filename_for_legacy_records(
    tmp_path: Path,
    make_client: Callable[[BalanceConfig | None], TestClient],
    auth_headers: dict[str, str],
) -> None:
    stored_name = "abcdef012345_lamp_white.png"
    (tmp_path / stored_name).write_bytes(b"lamp")
    legacy_meta = {
        "id": "abcdef012345",
        "filename": stored_name,
        "orig_name": "lamp.jpg",
        "url": f"/api/outputs/{stored_name}",
        "mime": "image/png",
        "size_kb": 1.0,
        "output_size": "1000x1000",
        "model": "gpt-image-2.5-sunburst",
        "quality": "medium",
        "elapsed": 1.2,
        "created_at": 1700000000,
    }
    (tmp_path / "abcdef012345.json").write_text(
        json.dumps(legacy_meta), encoding="utf-8"
    )

    client = make_client(None)
    response = client.get("/api/history", headers=auth_headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["export_filename"] == "lamp_white.png"


def test_download_zip_skips_occupied_numeric_suffix_without_overwriting(
    tmp_path: Path,
    make_client: Callable[[BalanceConfig | None], TestClient],
    auth_headers: dict[str, str],
) -> None:
    files = [
        "111111111111_item_white_2.png",
        "222222222222_item_white.png",
        "333333333333_item_white.png",
    ]
    for idx, name in enumerate(files):
        (tmp_path / name).write_bytes(f"file-{idx}".encode())

    client = make_client(None)
    response = client.post(
        "/api/download-zip",
        json={"filenames": files},
        headers=auth_headers,
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content), "r") as archive:
        assert archive.namelist() == [
            "item_white_2.png",
            "item_white.png",
            "item_white_3.png",
        ]


def test_generate_persists_and_returns_clean_export_filename(
    tmp_path: Path,
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    png_bytes = _make_png_bytes()
    fake_response = _FakeUpstreamResponse(
        {
            "data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}],
            "usage": {"total_tokens": 100},
        }
    )

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        response = client.post(
            "/api/generate",
            headers=api_env,
            data={"prompt": "pure white", "export_format": "png"},
            files={"file": ("SKU-42.jpg", png_bytes, "image/jpeg")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"].endswith("_SKU-42_white.png")
    assert body["export_filename"] == "SKU-42_white.png"
    persisted = json.loads((tmp_path / f"{body['id']}.json").read_text(encoding="utf-8"))
    assert persisted["export_filename"] == "SKU-42_white.png"
