from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from product_studio.app import preprocess_image
from product_studio.balance import BalanceConfig


def _encode_image(image: Image.Image, fmt: str = "PNG", **kwargs: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


class _FakeUpstreamResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_preprocess_normalizes_exif_orientation_and_flattens_transparency_to_white_jpeg() -> (
    None
):
    rgba = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    for x in range(120):
        for y in range(20):
            rgba.putpixel((x, y), (220, 40, 40, 255))
    exif = Image.Exif()
    exif[274] = 6  # Rotate 270 CW / 90 CW on display => 60x120
    raw_bytes = _encode_image(rgba, fmt="PNG", exif=exif)

    processed_bytes, report = preprocess_image(raw_bytes)

    decoded = Image.open(io.BytesIO(processed_bytes))
    assert decoded.format == "JPEG"
    assert decoded.mode == "RGB"
    assert decoded.size == (60, 120)
    assert report["orig_size"] == "60x120"
    assert report["processed_size"] == "60x120"
    # Transparent region (now on the left after 90 CW rotation) becomes white
    assert decoded.getpixel((5, 60)) == (255, 255, 255)


def test_preprocess_flattens_rgb_and_grayscale_png_transparency_keys_to_white() -> None:
    rgb_with_trns = Image.new("RGB", (32, 32), (0, 0, 0))
    raw_rgb = _encode_image(rgb_with_trns, fmt="PNG", transparency=(0, 0, 0))
    processed_rgb, _ = preprocess_image(raw_rgb)
    decoded_rgb = Image.open(io.BytesIO(processed_rgb))
    assert decoded_rgb.format == "JPEG"
    assert decoded_rgb.getpixel((16, 16)) == (255, 255, 255)

    gray_with_trns = Image.new("L", (32, 32), 0)
    raw_gray = _encode_image(gray_with_trns, fmt="PNG", transparency=0)
    processed_gray, _ = preprocess_image(raw_gray)
    decoded_gray = Image.open(io.BytesIO(processed_gray))
    assert decoded_gray.format == "JPEG"
    assert decoded_gray.getpixel((16, 16)) == (255, 255, 255)


def test_preprocess_keeps_tall_screenshots_and_small_images_uncropped_and_unscaled() -> (
    None
):
    tall = Image.new("RGB", (600, 1800), (120, 150, 200))
    processed_tall, report_tall = preprocess_image(_encode_image(tall, fmt="PNG"))
    decoded_tall = Image.open(io.BytesIO(processed_tall))
    assert decoded_tall.format == "JPEG"
    assert decoded_tall.size == (600, 1800)
    assert report_tall["processed_size"] == "600x1800"

    small = Image.new("RGB", (300, 300), (80, 90, 100))
    processed_small, report_small = preprocess_image(_encode_image(small, fmt="PNG"))
    decoded_small = Image.open(io.BytesIO(processed_small))
    assert decoded_small.format == "JPEG"
    assert decoded_small.size == (300, 300)
    assert report_small["processed_size"] == "300x300"


def test_preprocess_caps_high_resolution_images_at_2048px_max_edge() -> None:
    large = Image.new("RGB", (4000, 3000), (20, 140, 210))
    processed_bytes, report = preprocess_image(_encode_image(large, fmt="PNG"))
    decoded = Image.open(io.BytesIO(processed_bytes))
    assert decoded.format == "JPEG"
    assert decoded.size == (2048, 1536)
    assert report["orig_size"] == "4000x3000"
    assert report["processed_size"] == "2048x1536"


def test_generate_uploads_jpeg_and_ignores_removed_preprocess_toggle_params(
    api_env: dict[str, str],
    make_client: Callable[[BalanceConfig | None], TestClient],
) -> None:
    client = make_client(None)
    output_png = _encode_image(Image.new("RGB", (64, 64), (255, 255, 255)), fmt="PNG")
    fake_resp = _FakeUpstreamResponse(
        {"data": [{"b64_json": base64.b64encode(output_png).decode("ascii")}]}
    )
    tall_upload = _encode_image(Image.new("RGB", (1000, 2500), (10, 20, 30)), fmt="PNG")

    with patch(
        "product_studio.app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=fake_resp,
    ) as mock_post:
        resp = client.post(
            "/api/generate",
            headers=api_env,
            files={"file": ("phone.png", tall_upload, "image/png")},
            data={
                "prompt": "white background",
                "auto_crop_screenshot": "true",
                "max_input_edge": "512",
                "enhance_small": "true",
            },
        )

    assert resp.status_code == 200
    assert mock_post.await_args is not None
    uploaded_file = mock_post.await_args.kwargs["files"]["image"]
    filename, file_bytes, mime_type = uploaded_file
    assert filename == "input.jpg"
    assert mime_type == "image/jpeg"
    uploaded_image = Image.open(io.BytesIO(file_bytes))
    assert uploaded_image.format == "JPEG"
    assert uploaded_image.size == (819, 2048)
