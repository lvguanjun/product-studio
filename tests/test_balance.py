import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import app as app_module
from balance import (
    MODEL_PRICING,
    BalanceConfig,
    BalanceLedger,
    calculate_generation_cost,
    compute_key_fingerprint,
    load_balance_config_from_env,
)


class TestCalculateGenerationCost(unittest.TestCase):
    def test_sunburst_uses_token_details_pricing(self):
        usage = {
            "input_tokens": 1067,
            "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
            "output_tokens": 439,
            "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
            "total_tokens": 1506,
        }
        cost_usd, source = calculate_generation_cost("gpt-image-2.5-sunburst", usage)
        self.assertEqual(source, "usage")
        self.assertAlmostEqual(cost_usd, 0.021289, places=6)

    def test_gpt_image_1_5_and_mini_pricing(self):
        usage = {
            "input_tokens": 1000,
            "input_tokens_details": {"image_tokens": 800, "text_tokens": 200},
            "output_tokens": 500,
            "output_tokens_details": {"image_tokens": 500, "text_tokens": 0},
        }
        cost_15, src_15 = calculate_generation_cost("gpt-image-1.5", usage)
        self.assertEqual(src_15, "usage")
        # 800*8/1e6 + 200*5/1e6 + 500*32/1e6 = 0.0064 + 0.001 + 0.016 = 0.0234
        self.assertAlmostEqual(cost_15, 0.0234, places=6)

        cost_mini, src_mini = calculate_generation_cost("gpt-image-1-mini", usage)
        self.assertEqual(src_mini, "usage")
        # 800*2.5/1e6 + 200*2/1e6 + 500*8/1e6 = 0.002 + 0.0004 + 0.004 = 0.0064
        self.assertAlmostEqual(cost_mini, 0.0064, places=6)

    def test_missing_usage_or_unknown_model_falls_back_to_0_04(self):
        cost_empty, src_empty = calculate_generation_cost("gpt-image-2.5-sunburst", {})
        self.assertEqual(src_empty, "fallback")
        self.assertAlmostEqual(cost_empty, 0.04, places=6)

        cost_unknown, src_unknown = calculate_generation_cost(
            "gpt-image-future-9",
            {"input_tokens": 1000, "output_tokens": 500},
        )
        self.assertEqual(src_unknown, "fallback")
        self.assertAlmostEqual(cost_unknown, 0.04, places=6)

    def test_every_configured_app_model_has_explicit_pricing(self):
        for model_info in app_module.MODELS:
            self.assertIn(model_info["id"], MODEL_PRICING)


class TestBalanceLedger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.outputs_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_status_transitions_ok_warn_disabled_and_persists_charges(self):
        now = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        config = BalanceConfig(
            monthly_budget_usd=25.0,
            warn_threshold_usd=5.0,
            disable_threshold_usd=1.0,
            timezone_name="UTC",
        )
        ledger = BalanceLedger(self.outputs_dir, config_loader=lambda: config, now_fn=lambda: now)

        initial = ledger.get_status("sk-test-key-alpha")
        self.assertEqual(initial["status"], "ok")
        self.assertFalse(initial["disabled"])
        self.assertAlmostEqual(initial["remaining_usd"], 25.0, places=4)
        self.assertEqual(initial["billing_month"], "2026-11")
        self.assertEqual(initial["next_reset_at"], "2026-12-01T00:00:00+00:00")

        after_warn = ledger.record_charge(
            "sk-test-key-alpha",
            item_id="item1",
            model="gpt-image-2.5-sunburst",
            cost_usd=20.5,
            cost_source="usage",
            created_at=int(now.timestamp()),
        )
        self.assertEqual(after_warn["status"], "warn")
        self.assertFalse(after_warn["disabled"])
        self.assertAlmostEqual(after_warn["remaining_usd"], 4.5, places=4)
        self.assertEqual(after_warn["request_count"], 1)

        after_disable = ledger.record_charge(
            "sk-test-key-alpha",
            item_id="item2",
            model="gpt-image-2.5-sunburst",
            cost_usd=3.6,
            cost_source="usage",
            created_at=int(now.timestamp()),
        )
        self.assertEqual(after_disable["status"], "disabled")
        self.assertTrue(after_disable["disabled"])
        self.assertAlmostEqual(after_disable["remaining_usd"], 0.9, places=4)
        self.assertTrue(after_disable["disabled_reason"])

        reloaded = BalanceLedger(self.outputs_dir, config_loader=lambda: config, now_fn=lambda: now)
        snapshot = reloaded.get_status("sk-test-key-alpha")
        self.assertEqual(snapshot["status"], "disabled")
        self.assertAlmostEqual(snapshot["used_usd"], 24.1, places=4)

    def test_resets_automatically_on_first_of_next_month_in_configured_timezone(self):
        clock = [datetime(2026, 11, 30, 15, 59, tzinfo=timezone.utc)]
        config = BalanceConfig(
            monthly_budget_usd=25.0,
            warn_threshold_usd=5.0,
            disable_threshold_usd=1.0,
            timezone_name="Asia/Shanghai",
        )
        ledger = BalanceLedger(
            self.outputs_dir, config_loader=lambda: config, now_fn=lambda: clock[0]
        )

        status_nov = ledger.record_charge(
            "sk-key-tz",
            item_id="nov1",
            model="gpt-image-2.5-sunburst",
            cost_usd=24.5,
            cost_source="usage",
            created_at=int(clock[0].timestamp()),
        )
        self.assertEqual(status_nov["billing_month"], "2026-11")
        self.assertTrue(status_nov["disabled"])

        clock[0] = datetime(2026, 11, 30, 16, 1, tzinfo=timezone.utc)
        status_dec = ledger.get_status("sk-key-tz")
        self.assertEqual(status_dec["billing_month"], "2026-12")
        self.assertEqual(status_dec["status"], "ok")
        self.assertFalse(status_dec["disabled"])
        self.assertAlmostEqual(status_dec["remaining_usd"], 25.0, places=4)
        self.assertEqual(status_dec["next_reset_at"], "2027-01-01T00:00:00+08:00")

    def test_backfills_legacy_outputs_for_first_key_and_isolates_swapped_key(self):
        nov_ts = int(datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc).timestamp())
        oct_ts = int(datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc).timestamp())
        sample_usage = {
            "input_tokens": 1067,
            "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
            "output_tokens": 439,
            "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
        }
        (self.outputs_dir / "nov_legacy.json").write_text(
            json.dumps(
                {
                    "id": "nov_legacy",
                    "model": "gpt-image-2.5-sunburst",
                    "usage": sample_usage,
                    "created_at": nov_ts,
                }
            ),
            encoding="utf-8",
        )
        (self.outputs_dir / "oct_legacy.json").write_text(
            json.dumps(
                {
                    "id": "oct_legacy",
                    "model": "gpt-image-2.5-sunburst",
                    "usage": sample_usage,
                    "created_at": oct_ts,
                }
            ),
            encoding="utf-8",
        )

        now = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
        config = BalanceConfig()
        ledger = BalanceLedger(self.outputs_dir, config_loader=lambda: config, now_fn=lambda: now)

        first_key_status = ledger.get_status("sk-key-one")
        self.assertEqual(first_key_status["request_count"], 1)
        self.assertAlmostEqual(first_key_status["used_usd"], 0.021289, places=6)

        second_key_status = ledger.get_status("sk-key-two")
        self.assertEqual(second_key_status["request_count"], 0)
        self.assertAlmostEqual(second_key_status["used_usd"], 0.0, places=6)
        self.assertNotEqual(
            first_key_status["key_fingerprint"],
            second_key_status["key_fingerprint"],
        )

    def test_used_offset_scopes_to_month_when_configured(self):
        clock = [datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)]
        config = BalanceConfig(
            monthly_budget_usd=25.0,
            warn_threshold_usd=5.0,
            disable_threshold_usd=1.0,
            used_offset_usd=24.2,
            used_offset_month="2026-11",
        )
        ledger = BalanceLedger(
            self.outputs_dir, config_loader=lambda: config, now_fn=lambda: clock[0]
        )

        nov = ledger.get_status("sk-offset-key")
        self.assertTrue(nov["disabled"])
        self.assertAlmostEqual(nov["offset_used_usd"], 24.2, places=4)
        self.assertAlmostEqual(nov["remaining_usd"], 0.8, places=4)

        clock[0] = datetime(2026, 12, 1, 0, 5, tzinfo=timezone.utc)
        dec = ledger.get_status("sk-offset-key")
        self.assertFalse(dec["disabled"])
        self.assertAlmostEqual(dec["offset_used_usd"], 0.0, places=4)
        self.assertAlmostEqual(dec["remaining_usd"], 25.0, places=4)

    def test_non_finite_env_floats_fall_back_to_defaults(self):
        with patch.dict(
            os.environ,
            {
                "MONTHLY_BUDGET_USD": "inf",
                "BALANCE_WARN_THRESHOLD_USD": "nan",
                "BALANCE_DISABLE_THRESHOLD_USD": "-inf",
                "BALANCE_USED_OFFSET_USD": "NaN",
            },
            clear=False,
        ):
            cfg = load_balance_config_from_env()
        self.assertEqual(cfg.monthly_budget_usd, 25.0)
        self.assertEqual(cfg.warn_threshold_usd, 5.0)
        self.assertEqual(cfg.disable_threshold_usd, 1.0)
        self.assertEqual(cfg.used_offset_usd, 0.0)

    def test_corrupt_bucket_rebuilds_and_still_backfills_legacy_outputs(self):
        nov_ts = int(datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc).timestamp())
        (self.outputs_dir / "legacy_item.json").write_text(
            json.dumps(
                {
                    "id": "legacy_item",
                    "model": "gpt-image-2.5-sunburst",
                    "cost_usd": 0.05,
                    "created_at": nov_ts,
                }
            ),
            encoding="utf-8",
        )
        key = "sk-corrupt-test"
        fp = compute_key_fingerprint(key)
        ledger_dir = self.outputs_dir / ".balance"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        (ledger_dir / f"{fp}_2026-11.json").write_text("{corrupt json", encoding="utf-8")

        now = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
        ledger = BalanceLedger(
            self.outputs_dir, config_loader=BalanceConfig, now_fn=lambda: now
        )
        status = ledger.get_status(key)
        self.assertEqual(status["request_count"], 1)
        self.assertAlmostEqual(status["used_usd"], 0.05, places=6)


if __name__ == "__main__":
    unittest.main()
