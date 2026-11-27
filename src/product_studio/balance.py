import hashlib
import json
import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FALLBACK_IMAGE_COST_USD = 0.04
TOKENS_PER_MILLION = 1_000_000.0
DEFAULT_MONTHLY_BUDGET_USD = 25.0
DEFAULT_WARN_THRESHOLD_USD = 5.0
DEFAULT_DISABLE_THRESHOLD_USD = 1.0
DEFAULT_BILLING_TIMEZONE = "UTC"

CostSource = Literal["usage", "fallback"]
BalanceState = Literal["ok", "warn", "disabled", "unconfigured"]


@dataclass(frozen=True)
class ModelTokenPricing:
    input_text_per_million: float
    input_image_per_million: float
    output_text_per_million: float
    output_image_per_million: float


@dataclass(frozen=True)
class BalanceConfig:
    monthly_budget_usd: float = DEFAULT_MONTHLY_BUDGET_USD
    warn_threshold_usd: float = DEFAULT_WARN_THRESHOLD_USD
    disable_threshold_usd: float = DEFAULT_DISABLE_THRESHOLD_USD
    timezone_name: str = DEFAULT_BILLING_TIMEZONE
    used_offset_usd: float = 0.0
    used_offset_month: str = ""


@dataclass(frozen=True)
class BillingPeriod:
    month: str
    timezone_name: str
    start_ts: float
    next_reset_ts: float
    next_reset_iso: str


MODEL_PRICING: dict[str, ModelTokenPricing] = {
    "gpt-image-2.5-sunburst": ModelTokenPricing(5.0, 8.0, 10.0, 30.0),
    "gpt-image-2.5-flare": ModelTokenPricing(5.0, 8.0, 10.0, 30.0),
    "gpt-image-2": ModelTokenPricing(5.0, 8.0, 10.0, 30.0),
    "gpt-image-1.5": ModelTokenPricing(5.0, 8.0, 10.0, 32.0),
    "gpt-image-1-mini": ModelTokenPricing(2.0, 2.5, 2.0, 8.0),
}


def _safe_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _parse_non_negative_float(raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except ValueError:
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, parsed)


def load_balance_config_from_env() -> BalanceConfig:
    timezone_name = (os.getenv("BILLING_TIMEZONE") or DEFAULT_BILLING_TIMEZONE).strip()
    return BalanceConfig(
        monthly_budget_usd=_parse_non_negative_float(
            os.getenv("MONTHLY_BUDGET_USD"), DEFAULT_MONTHLY_BUDGET_USD
        ),
        warn_threshold_usd=_parse_non_negative_float(
            os.getenv("BALANCE_WARN_THRESHOLD_USD"), DEFAULT_WARN_THRESHOLD_USD
        ),
        disable_threshold_usd=_parse_non_negative_float(
            os.getenv("BALANCE_DISABLE_THRESHOLD_USD"), DEFAULT_DISABLE_THRESHOLD_USD
        ),
        timezone_name=timezone_name or DEFAULT_BILLING_TIMEZONE,
        used_offset_usd=_parse_non_negative_float(
            os.getenv("BALANCE_USED_OFFSET_USD"), 0.0
        ),
        used_offset_month=(os.getenv("BALANCE_USED_OFFSET_MONTH") or "").strip(),
    )


def compute_key_fingerprint(api_key: str) -> str:
    cleaned = api_key.strip()
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


def resolve_billing_period(now: datetime, timezone_name: str) -> BillingPeriod:
    resolved_name = timezone_name or DEFAULT_BILLING_TIMEZONE
    try:
        tz = ZoneInfo(resolved_name)
    except ZoneInfoNotFoundError:
        resolved_name = DEFAULT_BILLING_TIMEZONE
        tz = ZoneInfo(DEFAULT_BILLING_TIMEZONE)

    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local_now = aware_now.astimezone(tz)
    period_start = datetime(local_now.year, local_now.month, 1, 0, 0, 0, tzinfo=tz)
    if local_now.month == 12:
        next_reset = datetime(local_now.year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        next_reset = datetime(
            local_now.year, local_now.month + 1, 1, 0, 0, 0, tzinfo=tz
        )

    return BillingPeriod(
        month=f"{local_now.year:04d}-{local_now.month:02d}",
        timezone_name=resolved_name,
        start_ts=period_start.timestamp(),
        next_reset_ts=next_reset.timestamp(),
        next_reset_iso=next_reset.isoformat(),
    )


def _extract_token_pair(
    usage: dict[str, Any],
    details_key: str,
    total_key: str,
) -> tuple[int, int]:
    details = usage.get(details_key)
    if isinstance(details, dict) and (
        "image_tokens" in details or "text_tokens" in details
    ):
        return (
            _safe_non_negative_int(details.get("image_tokens")),
            _safe_non_negative_int(details.get("text_tokens")),
        )
    return _safe_non_negative_int(usage.get(total_key)), 0


def calculate_generation_cost(
    model: str,
    usage: dict[str, Any] | None,
) -> tuple[float, CostSource]:
    pricing = MODEL_PRICING.get(model)
    if pricing is None or not isinstance(usage, dict) or not usage:
        return FALLBACK_IMAGE_COST_USD, "fallback"

    input_image_tokens, input_text_tokens = _extract_token_pair(
        usage, "input_tokens_details", "input_tokens"
    )
    output_image_tokens, output_text_tokens = _extract_token_pair(
        usage, "output_tokens_details", "output_tokens"
    )

    total_counted = (
        input_image_tokens
        + input_text_tokens
        + output_image_tokens
        + output_text_tokens
    )
    if total_counted == 0:
        return FALLBACK_IMAGE_COST_USD, "fallback"

    cost_usd = (
        input_text_tokens * pricing.input_text_per_million
        + input_image_tokens * pricing.input_image_per_million
        + output_text_tokens * pricing.output_text_per_million
        + output_image_tokens * pricing.output_image_per_million
    ) / TOKENS_PER_MILLION
    return round(cost_usd, 6), "usage"


def resolve_record_cost(record: dict[str, Any]) -> tuple[float, CostSource]:
    raw_cost = record.get("cost_usd")
    if isinstance(raw_cost, (int, float)) and math.isfinite(raw_cost) and raw_cost >= 0:
        raw_source = str(record.get("cost_source") or "usage")
        source: CostSource = "fallback" if raw_source == "fallback" else "usage"
        return round(float(raw_cost), 6), source
    return calculate_generation_cost(
        str(record.get("model") or ""), record.get("usage")
    )


def _sum_entries_cost(entries: list[dict[str, Any]]) -> float:
    return round(sum(float(entry.get("cost_usd", 0.0)) for entry in entries), 6)


class BalanceLedger:
    def __init__(
        self,
        outputs_dir: Path,
        *,
        config_loader: Callable[[], BalanceConfig] = load_balance_config_from_env,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._outputs_dir = Path(outputs_dir)
        self._ledger_dir = self._outputs_dir / ".balance"
        self._config_loader = config_loader
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()

    def _bucket_path(self, key_fp: str, billing_month: str) -> Path:
        return self._ledger_dir / f"{key_fp}_{billing_month}.json"

    def _write_bucket(self, path: Path, payload: dict[str, Any]) -> None:
        self._ledger_dir.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, path)

    def _load_or_init_bucket(
        self, key_fp: str, period: BillingPeriod
    ) -> dict[str, Any]:
        bucket_path = self._bucket_path(key_fp, period.month)
        if bucket_path.exists():
            try:
                loaded = json.loads(bucket_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
                    return loaded
            except (OSError, ValueError):
                pass

        other_month_ledgers = (
            [
                candidate
                for candidate in self._ledger_dir.glob(f"*_{period.month}.json")
                if candidate != bucket_path
            ]
            if self._ledger_dir.exists()
            else []
        )
        allow_legacy_without_fp = len(other_month_ledgers) == 0

        entries: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        if self._outputs_dir.exists():
            for meta_file in sorted(self._outputs_dir.glob("*.json")):
                try:
                    record = json.loads(meta_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                created_at = record.get("created_at")
                if not isinstance(created_at, (int, float)):
                    continue
                if not (period.start_ts <= float(created_at) < period.next_reset_ts):
                    continue

                record_fp = str(record.get("key_fingerprint") or "").strip()
                if record_fp:
                    if record_fp != key_fp:
                        continue
                elif not allow_legacy_without_fp:
                    continue

                item_id = str(record.get("id") or meta_file.stem)
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                cost_usd, cost_source = resolve_record_cost(record)
                entries.append(
                    {
                        "item_id": item_id,
                        "model": str(record.get("model") or ""),
                        "cost_usd": cost_usd,
                        "cost_source": cost_source,
                        "created_at": int(created_at),
                    }
                )

        tracked_used_usd = _sum_entries_cost(entries)
        bucket = {
            "key_fingerprint": key_fp,
            "billing_month": period.month,
            "tracked_used_usd": tracked_used_usd,
            "entries": entries,
        }
        self._write_bucket(bucket_path, bucket)
        return bucket

    def _build_status(
        self,
        *,
        api_key: str,
        config: BalanceConfig,
        period: BillingPeriod,
        bucket: dict[str, Any] | None,
    ) -> dict[str, Any]:
        key_fp = compute_key_fingerprint(api_key)
        configured = bool(key_fp and bucket is not None)
        tracked_used = 0.0
        offset_used = 0.0
        used_usd = 0.0
        remaining_usd = 0.0
        request_count = 0
        status: BalanceState = "unconfigured"
        disabled = True
        disabled_reason = "未在 .env 中检测到 API_KEY 或 OPENAI_API_KEY"

        if configured and bucket is not None:
            entries = bucket.get("entries") or []
            request_count = len(entries)
            tracked_used = _sum_entries_cost(entries)
            offset_applies = (
                not config.used_offset_month or config.used_offset_month == period.month
            )
            offset_used = round(config.used_offset_usd if offset_applies else 0.0, 6)
            used_usd = round(tracked_used + offset_used, 6)
            raw_remaining = config.monthly_budget_usd - used_usd
            remaining_usd = round(max(0.0, raw_remaining), 6)

            if raw_remaining <= config.disable_threshold_usd:
                status = "disabled"
                disabled = True
                disabled_reason = (
                    f"当前 Key 估算余额 (${remaining_usd:.2f}) 已低于或等于禁用阈值 "
                    f"(${config.disable_threshold_usd:.2f})，已暂停生图，将于 {period.next_reset_iso} 自动重置"
                )
            elif raw_remaining <= config.warn_threshold_usd:
                status = "warn"
                disabled = False
                disabled_reason = ""
            else:
                status = "ok"
                disabled = False
                disabled_reason = ""

        return {
            "configured": configured,
            "key_fingerprint": key_fp if configured else "",
            "billing_month": period.month,
            "timezone": period.timezone_name,
            "next_reset_at": period.next_reset_iso,
            "monthly_budget_usd": round(config.monthly_budget_usd, 6),
            "tracked_used_usd": tracked_used,
            "offset_used_usd": offset_used,
            "used_usd": used_usd,
            "remaining_usd": remaining_usd,
            "warn_threshold_usd": round(config.warn_threshold_usd, 6),
            "disable_threshold_usd": round(config.disable_threshold_usd, 6),
            "status": status,
            "disabled": disabled,
            "disabled_reason": disabled_reason,
            "request_count": request_count,
            "is_estimated": True,
        }

    def get_status(self, api_key: str) -> dict[str, Any]:
        with self._lock:
            config = self._config_loader()
            period = resolve_billing_period(self._now_fn(), config.timezone_name)
            key_fp = compute_key_fingerprint(api_key)
            bucket = self._load_or_init_bucket(key_fp, period) if key_fp else None
            return self._build_status(
                api_key=api_key,
                config=config,
                period=period,
                bucket=bucket,
            )

    def record_charge(
        self,
        api_key: str,
        *,
        item_id: str,
        model: str,
        cost_usd: float,
        cost_source: str,
        created_at: int,
    ) -> dict[str, Any]:
        with self._lock:
            config = self._config_loader()
            period = resolve_billing_period(self._now_fn(), config.timezone_name)
            key_fp = compute_key_fingerprint(api_key)
            if not key_fp:
                return self._build_status(
                    api_key=api_key,
                    config=config,
                    period=period,
                    bucket=None,
                )
            bucket = self._load_or_init_bucket(key_fp, period)
            entries: list[dict[str, Any]] = bucket.setdefault("entries", [])
            if not any(entry.get("item_id") == item_id for entry in entries):
                entries.append(
                    {
                        "item_id": item_id,
                        "model": model,
                        "cost_usd": round(max(0.0, float(cost_usd)), 6),
                        "cost_source": cost_source,
                        "created_at": int(created_at),
                    }
                )
                bucket["tracked_used_usd"] = _sum_entries_cost(entries)
                self._write_bucket(self._bucket_path(key_fp, period.month), bucket)
            return self._build_status(
                api_key=api_key,
                config=config,
                period=period,
                bucket=bucket,
            )
