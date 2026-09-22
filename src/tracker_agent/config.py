"""Loads settings.yaml + sheet.yaml + .env into pydantic models."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(value: object) -> object:
    if isinstance(value, str):
        match = _ENV_VAR_RE.fullmatch(value.strip())
        if match:
            return os.environ.get(match.group(1), "")
        return value
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


class SheetSettings(BaseModel):
    id: str = ""
    id_demo: str = ""


class FlagSettings(BaseModel):
    due_soon_days: int = 7
    stale_days: int = 10
    inspection_risk_days: int = 3
    llm_soft_flags: bool = True


class DigestSettings(BaseModel):
    recipients: list[str] = []
    send_day: str = "friday"
    send_hour: int = 7


class RagSettings(BaseModel):
    chunk_size_tokens: int = 800
    chunk_overlap_tokens: int = 100
    top_k: int = 8


class Settings(BaseModel):
    model: str
    sheet: SheetSettings = SheetSettings()
    flags: FlagSettings = FlagSettings()
    digest: DigestSettings = DigestSettings()
    rag: RagSettings = RagSettings()


class SheetConfig(BaseModel):
    """Single-tab column mapping for the Projects tab (config/sheet.yaml)."""

    tab: str
    key_column: str
    columns: dict[str, str] = {}
    ai_columns: dict[str, str] = {}

    def ai_column_headers(self) -> set[str]:
        """The only headers write_ai_cells() may touch."""
        return set(self.ai_columns.values())


def load_settings(path: Path | None = None) -> Settings:
    path = path or REPO_ROOT / "config" / "settings.yaml"
    load_dotenv(REPO_ROOT / ".env", override=False)
    raw = yaml.safe_load(path.read_text()) or {}
    return Settings.model_validate(_expand_env(raw))


def load_sheet_config(path: Path | None = None) -> SheetConfig:
    path = path or REPO_ROOT / "config" / "sheet.yaml"
    raw = yaml.safe_load(path.read_text()) or {}
    return SheetConfig.model_validate(raw)
