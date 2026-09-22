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


class FlagSettings(BaseModel):
    our_move_days: int = 2
    chase_days: int = 4
    due_soon_days: int = 7
    stale_days: int = 10


class ReportSettings(BaseModel):
    recipients: list[str] = []
    send_day: str = "friday"
    send_hour: int = 7


class RagSettings(BaseModel):
    chunk_size_tokens: int = 800
    chunk_overlap_tokens: int = 100
    top_k: int = 8


class Settings(BaseModel):
    model: str
    flags: FlagSettings = FlagSettings()
    report: ReportSettings = ReportSettings()
    rag: RagSettings = RagSettings()


class SpreadsheetConfig(BaseModel):
    project_id: str
    sheet_id_env: str
    changelog_tab: str | None = None  # overrides SheetConfig.changelog_tab for this sheet only

    def sheet_id(self) -> str:
        return os.environ.get(self.sheet_id_env, "")


class DateColumnConfig(BaseModel):
    header: str = "DATE"
    fallback_after: str  # if the header is blank, use the column right after this one


class ColumnsConfig(BaseModel):
    sub: str
    item: str
    date: DateColumnConfig
    status: str
    details: str
    notes: str


class SheetConfig(BaseModel):
    """Tab-detection rules and column mapping (config/sheet.yaml).

    Human columns (sub/item/date/status/details/notes) are read-only.
    ai_columns are the only headers write_ai_cells() may touch on the
    latest weekly tab. agent_tabs are wholly agent-owned (AI Brief, Ask,
    AI Log) — every cell on those tabs is fair game.
    """

    spreadsheets: list[SpreadsheetConfig]
    changelog_tab: str = "auto"
    weekly_tab_regex: str
    ignore_tab_regex: str
    columns: ColumnsConfig
    ai_columns: dict[str, str]
    agent_tabs: list[str] = []
    done_status: list[str] = []
    done_details: list[str] = []  # DETAILS values meaning nobody holds the ball
    ball_in_our_court: list[str] = []
    waiting_on_others: list[str] = []

    def ai_column_headers(self) -> set[str]:
        """The only headers write_ai_cells() may touch on the latest weekly tab."""
        return set(self.ai_columns.values())


def load_settings(path: Path | None = None) -> Settings:
    path = path or REPO_ROOT / "config" / "settings.yaml"
    load_dotenv(REPO_ROOT / ".env", override=False)
    raw = yaml.safe_load(path.read_text()) or {}
    return Settings.model_validate(_expand_env(raw))


def load_sheet_config(path: Path | None = None) -> SheetConfig:
    path = path or REPO_ROOT / "config" / "sheet.yaml"
    load_dotenv(REPO_ROOT / ".env", override=False)
    raw = yaml.safe_load(path.read_text()) or {}
    return SheetConfig.model_validate(raw)
