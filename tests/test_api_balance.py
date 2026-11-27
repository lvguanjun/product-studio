import base64
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

import app as app_module
from balance import BalanceConfig, BalanceLedger


def _make_png_bytes(color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeUpstreamResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestApiBalanceIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.outputs_dir = Path(self.temp_dir.name)
        self.orig_output_dir = app_module.OUTPUT_DIR
        self.orig_ledger = getattr(app_module, "balance_ledger", None)
        self.orig_env = dict(os.environ)

        os.environ["ACCESS_KEY"] = "test-access"
        os.environ["API_KEY"] = "sk-proj-test-balance-key"
        os.environ["MONTHLY_BUDGET_USD"] = "25"
        os.environ["BALANCE_WARN_THRESHOLD_USD"] = "5"
        os.environ["BALANCE_DISABLE_THRESHOLD_USD"] = "1"
        os.environ["BILLING_TIMEZONE"] = "UTC"
        os.environ.pop("BALANCE_USED_OFFSET_USD", None)
        os.environ.pop("BALANCE_USED_OFFSET_MONTH", None)

        app_module.OUTPUT_DIR = self.outputs_dir
        self.now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
        self.client = TestClient(app_module.app)
        token = base64.b64encode(b"test-access:test-access").decode("ascii")
        self.auth_headers = {"Authorization": f"Basic {token}"}

    def tearDown(self):
        app_module.OUTPUT_DIR = self.orig_output_dir
        if self.orig_ledger is not None:
            app_module.balance_ledger = self.orig_ledger
        os.environ.clear()
        os.environ.update(self.orig_env)
        self.temp_dir.cleanup()

    def _install_ledger(self, config: BalanceConfig | None = None):
        if config is None:
            app_module.balance_ledger = BalanceLedger(
                self.outputs_dir, now_fn=lambda: self.now
            )
        else:
            app_module.balance_ledger = BalanceLedger(
                self.outputs_dir,
                config_loader=lambda: config,
                now_fn=lambda: self.now,
            )

    def test_config_and_balance_endpoints_expose_balance_snapshot(self):
        self._install_ledger()
        config_resp = self.client.get("/api/config", headers=self.auth_headers)
        self.assertEqual(config_resp.status_code, 200)
        config_data = config_resp.json()
        self.assertIn("balance", config_data)
        self.assertEqual(config_data["balance"]["monthly_budget_usd"], 25.0)
        self.assertEqual(config_data["balance"]["remaining_usd"], 25.0)
        self.assertEqual(config_data["balance"]["status"], "ok")

        bal_resp = self.client.get("/api/balance", headers=self.auth_headers)
        self.assertEqual(bal_resp.status_code, 200)
        self.assertEqual(bal_resp.json()["billing_month"], "2026-11")

    def test_generate_blocks_with_402_when_below_threshold_while_history_and_download_work(self):
        self._install_ledger(
            BalanceConfig(
                monthly_budget_usd=25.0,
                warn_threshold_usd=5.0,
                disable_threshold_usd=1.0,
                used_offset_usd=24.2,
            )
        )
        # Seed an existing generated file + metadata to verify history/download stay enabled
        sample_img = _make_png_bytes((255, 255, 255))
        (self.outputs_dir / "abc123_demo_white.png").write_bytes(sample_img)
        (self.outputs_dir / "abc123.json").write_text(
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
                    "created_at": int(self.now.timestamp()) - 3600,
                }
            ),
            encoding="utf-8",
        )

        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            gen_resp = self.client.post(
                "/api/generate",
                headers=self.auth_headers,
                files={"file": ("item.png", _make_png_bytes(), "image/png")},
                data={"prompt": "white background"},
            )
            self.assertEqual(gen_resp.status_code, 402)
            body = gen_resp.json()
            self.assertEqual(body["code"], "BALANCE_BELOW_THRESHOLD")
            self.assertTrue(body["balance"]["disabled"])
            mock_post.assert_not_awaited()

        hist_resp = self.client.get("/api/history", headers=self.auth_headers)
        self.assertEqual(hist_resp.status_code, 200)
        items = hist_resp.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["cost_usd"], 0.021289, places=6)

        file_resp = self.client.get(
            "/api/outputs/abc123_demo_white.png", headers=self.auth_headers
        )
        self.assertEqual(file_resp.status_code, 200)

        zip_resp = self.client.post(
            "/api/download-zip",
            headers=self.auth_headers,
            json={"filenames": ["abc123_demo_white.png"]},
        )
        self.assertEqual(zip_resp.status_code, 200)

    def test_generate_charges_ledger_and_returns_cost_and_updated_balance(self):
        self._install_ledger()
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
            "app.httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=fake_resp,
        ):
            resp = self.client.post(
                "/api/generate",
                headers=self.auth_headers,
                files={"file": ("shoe.png", _make_png_bytes(), "image/png")},
                data={"prompt": "white background", "model": "gpt-image-2.5-sunburst"},
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertAlmostEqual(payload["cost_usd"], 0.021289, places=6)
        self.assertEqual(payload["cost_source"], "usage")
        self.assertAlmostEqual(payload["balance"]["used_usd"], 0.021289, places=6)
        self.assertAlmostEqual(
            payload["balance"]["remaining_usd"], 25.0 - 0.021289, places=6
        )

        saved_meta = json.loads(
            (self.outputs_dir / f"{payload['id']}.json").read_text(encoding="utf-8")
        )
        self.assertAlmostEqual(saved_meta["cost_usd"], 0.021289, places=6)
        self.assertTrue(saved_meta["key_fingerprint"])


if __name__ == "__main__":
    unittest.main()
