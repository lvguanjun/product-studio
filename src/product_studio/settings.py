from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ModelId = Literal[
    "gpt-image-2.5-sunburst",
    "gpt-image-2.5-flare",
    "gpt-image-2",
    "gpt-image-1.5",
    "gpt-image-1-mini",
]
QualityLevel = Literal["low", "medium", "high"]
ExportSize = Literal["1000x1000", "800x800", "native"]
ExportFormat = Literal["png", "jpg", "webp"]


class AdvancedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: ModelId
    quality: QualityLevel
    concurrency: int = Field(ge=1, le=4)
    export_size: ExportSize
    export_format: ExportFormat


FACTORY_DEFAULTS = AdvancedSettings(
    model="gpt-image-2.5-sunburst",
    quality="medium",
    concurrency=2,
    export_size="1000x1000",
    export_format="png",
)


class SettingsStore:
    def __init__(self, outputs_dir: Path) -> None:
        self._settings_dir = Path(outputs_dir) / ".settings"
        self._file_path = self._settings_dir / "global_defaults.json"
        self._lock = threading.Lock()

    def load(self) -> AdvancedSettings:
        with self._lock:
            return self._read_unlocked()

    def save(self, settings: AdvancedSettings) -> AdvancedSettings:
        with self._lock:
            self._write_unlocked(settings)
            return settings

    def _read_unlocked(self) -> AdvancedSettings:
        if not self._file_path.exists():
            return FACTORY_DEFAULTS
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return FACTORY_DEFAULTS
        if not isinstance(raw, dict):
            return FACTORY_DEFAULTS

        merged: dict[str, object] = FACTORY_DEFAULTS.model_dump()
        for field_name in AdvancedSettings.model_fields:
            if field_name not in raw:
                continue
            candidate = {**merged, field_name: raw[field_name]}
            try:
                AdvancedSettings.model_validate(candidate)
            except ValidationError:
                continue
            merged[field_name] = raw[field_name]
        return AdvancedSettings.model_validate(merged)

    def _write_unlocked(self, settings: AdvancedSettings) -> None:
        self._settings_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self._file_path.with_name(
            f"{self._file_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temp_path.write_text(
            json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self._file_path)
