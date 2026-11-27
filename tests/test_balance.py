from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from product_studio.app import MODELS
from product_studio.balance import (
    MODEL_PRICING,
    BalanceConfig,
    BalanceLedger,
    calculate_generation_cost,
    compute_key_fingerprint,
    load_balance_config_from_env,
)


def test_sunburst_uses_token_details_pricing() -> None:
    usage = {
        "input_tokens": 1067,
        "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
        "output_tokens": 439,
        "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
        "total_tokens": 1506,
    }
    cost_usd, source = calculate_generation_cost("gpt-image-2.5-sunburst", usage)
    assert source == "usage"
    assert cost_usd == pytest.approx(0.021289, abs=1e-6)


def test_gpt_image_1_5_and_mini_pricing() -> None:
    usage = {
        "input_tokens": 1000,
        "input_tokens_details": {"image_tokens": 800, "text_tokens": 200},
        "output_tokens": 500,
        "output_tokens_details": {"image_tokens": 500, "text_tokens": 0},
    }
    cost_15, src_15 = calculate_generation_cost("gpt-image-1.5", usage)
    assert src_15 == "usage"
    assert cost_15 == pytest.approx(0.0234, abs=1e-6)

    cost_mini, src_mini = calculate_generation_cost("gpt-image-1-mini", usage)
    assert src_mini == "usage"
    assert cost_mini == pytest.approx(0.0064, abs=1e-6)


def test_missing_usage_or_unknown_model_falls_back_to_0_04() -> None:
    cost_empty, src_empty = calculate_generation_cost("gpt-image-2.5-sunburst", {})
    assert src_empty == "fallback"
    assert cost_empty == pytest.approx(0.04, abs=1e-6)

    cost_unknown, src_unknown = calculate_generation_cost(
        "gpt-image-future-9",
        {"input_tokens": 1000, "output_tokens": 500},
    )
    assert src_unknown == "fallback"
    assert cost_unknown == pytest.approx(0.04, abs=1e-6)


def test_every_configured_app_model_has_explicit_pricing() -> None:
    for model_info in MODELS:
        assert model_info["id"] in MODEL_PRICING


def test_status_transitions_ok_warn_disabled_and_persists_charges(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    config = BalanceConfig(
        monthly_budget_usd=25.0,
        warn_threshold_usd=5.0,
        disable_threshold_usd=1.0,
        timezone_name="UTC",
    )
    ledger = BalanceLedger(tmp_path, config_loader=lambda: config, now_fn=lambda: now)

    initial = ledger.get_status("sk-test-key-alpha")
    assert initial["status"] == "ok"
    assert not initial["disabled"]
    assert initial["remaining_usd"] == pytest.approx(25.0, abs=1e-4)
    assert initial["billing_month"] == "2026-11"
    assert initial["next_reset_at"] == "2026-12-01T00:00:00+00:00"

    after_warn = ledger.record_charge(
        "sk-test-key-alpha",
        item_id="item1",
        model="gpt-image-2.5-sunburst",
        cost_usd=20.5,
        cost_source="usage",
        created_at=int(now.timestamp()),
    )
    assert after_warn["status"] == "warn"
    assert not after_warn["disabled"]
    assert after_warn["remaining_usd"] == pytest.approx(4.5, abs=1e-4)
    assert after_warn["request_count"] == 1

    after_disable = ledger.record_charge(
        "sk-test-key-alpha",
        item_id="item2",
        model="gpt-image-2.5-sunburst",
        cost_usd=3.6,
        cost_source="usage",
        created_at=int(now.timestamp()),
    )
    assert after_disable["status"] == "disabled"
    assert after_disable["disabled"]
    assert after_disable["remaining_usd"] == pytest.approx(0.9, abs=1e-4)
    assert after_disable["disabled_reason"]

    reloaded = BalanceLedger(tmp_path, config_loader=lambda: config, now_fn=lambda: now)
    snapshot = reloaded.get_status("sk-test-key-alpha")
    assert snapshot["status"] == "disabled"
    assert snapshot["used_usd"] == pytest.approx(24.1, abs=1e-4)


def test_resets_automatically_on_first_of_next_month_in_configured_timezone(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 11, 30, 15, 59, tzinfo=UTC)]
    config = BalanceConfig(
        monthly_budget_usd=25.0,
        warn_threshold_usd=5.0,
        disable_threshold_usd=1.0,
        timezone_name="Asia/Shanghai",
    )
    ledger = BalanceLedger(
        tmp_path, config_loader=lambda: config, now_fn=lambda: clock[0]
    )

    status_nov = ledger.record_charge(
        "sk-key-tz",
        item_id="nov1",
        model="gpt-image-2.5-sunburst",
        cost_usd=24.5,
        cost_source="usage",
        created_at=int(clock[0].timestamp()),
    )
    assert status_nov["billing_month"] == "2026-11"
    assert status_nov["disabled"]

    clock[0] = datetime(2026, 11, 30, 16, 1, tzinfo=UTC)
    status_dec = ledger.get_status("sk-key-tz")
    assert status_dec["billing_month"] == "2026-12"
    assert status_dec["status"] == "ok"
    assert not status_dec["disabled"]
    assert status_dec["remaining_usd"] == pytest.approx(25.0, abs=1e-4)
    assert status_dec["next_reset_at"] == "2027-01-01T00:00:00+08:00"


def test_backfills_legacy_outputs_for_first_key_and_isolates_swapped_key(
    tmp_path: Path,
) -> None:
    nov_ts = int(datetime(2026, 11, 20, 10, 0, tzinfo=UTC).timestamp())
    oct_ts = int(datetime(2026, 10, 28, 10, 0, tzinfo=UTC).timestamp())
    sample_usage = {
        "input_tokens": 1067,
        "input_tokens_details": {"image_tokens": 928, "text_tokens": 139},
        "output_tokens": 439,
        "output_tokens_details": {"image_tokens": 439, "text_tokens": 0},
    }
    (tmp_path / "nov_legacy.json").write_text(
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
    (tmp_path / "oct_legacy.json").write_text(
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

    now = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
    config = BalanceConfig()
    ledger = BalanceLedger(tmp_path, config_loader=lambda: config, now_fn=lambda: now)

    first_key_status = ledger.get_status("sk-key-one")
    assert first_key_status["request_count"] == 1
    assert first_key_status["used_usd"] == pytest.approx(0.021289, abs=1e-6)

    second_key_status = ledger.get_status("sk-key-two")
    assert second_key_status["request_count"] == 0
    assert second_key_status["used_usd"] == pytest.approx(0.0, abs=1e-6)
    assert first_key_status["key_fingerprint"] != second_key_status["key_fingerprint"]


def test_used_offset_scopes_to_month_when_configured(tmp_path: Path) -> None:
    clock = [datetime(2026, 11, 26, 10, 0, tzinfo=UTC)]
    config = BalanceConfig(
        monthly_budget_usd=25.0,
        warn_threshold_usd=5.0,
        disable_threshold_usd=1.0,
        used_offset_usd=24.2,
        used_offset_month="2026-11",
    )
    ledger = BalanceLedger(
        tmp_path, config_loader=lambda: config, now_fn=lambda: clock[0]
    )

    nov = ledger.get_status("sk-offset-key")
    assert nov["disabled"]
    assert nov["offset_used_usd"] == pytest.approx(24.2, abs=1e-4)
    assert nov["remaining_usd"] == pytest.approx(0.8, abs=1e-4)

    clock[0] = datetime(2026, 12, 1, 0, 5, tzinfo=UTC)
    dec = ledger.get_status("sk-offset-key")
    assert not dec["disabled"]
    assert dec["offset_used_usd"] == pytest.approx(0.0, abs=1e-4)
    assert dec["remaining_usd"] == pytest.approx(25.0, abs=1e-4)


def test_non_finite_env_floats_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "inf")
    monkeypatch.setenv("BALANCE_WARN_THRESHOLD_USD", "nan")
    monkeypatch.setenv("BALANCE_DISABLE_THRESHOLD_USD", "-inf")
    monkeypatch.setenv("BALANCE_USED_OFFSET_USD", "NaN")

    cfg = load_balance_config_from_env()
    assert cfg.monthly_budget_usd == 25.0
    assert cfg.warn_threshold_usd == 5.0
    assert cfg.disable_threshold_usd == 1.0
    assert cfg.used_offset_usd == 0.0


def test_corrupt_bucket_rebuilds_and_still_backfills_legacy_outputs(
    tmp_path: Path,
) -> None:
    nov_ts = int(datetime(2026, 11, 20, 10, 0, tzinfo=UTC).timestamp())
    (tmp_path / "legacy_item.json").write_text(
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
    ledger_dir = tmp_path / ".balance"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / f"{fp}_2026-11.json").write_text("{corrupt json", encoding="utf-8")

    now = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
    ledger = BalanceLedger(tmp_path, config_loader=BalanceConfig, now_fn=lambda: now)
    status = ledger.get_status(key)
    assert status["request_count"] == 1
    assert status["used_usd"] == pytest.approx(0.05, abs=1e-6)
