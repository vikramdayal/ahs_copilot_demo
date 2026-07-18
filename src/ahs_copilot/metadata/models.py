from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceLocator(StrictModel):
    workbook_name: str
    workbook_sha256: str
    sheet_name: str
    row_number: int | None = None
    cell_range: str | None = None
    original_text: str | None = None


class SourceFileRecord(StrictModel):
    """Day 2 logical source-file contract used by the execution resolver."""

    source_file_id: str
    name: str
    access_level: Literal["PUF", "IUF", "UNKNOWN"]
    sample_scope: str
    relation: str
    grain: str
    join_keys: list[str]
    parent_source_file_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_locators: list[SourceLocator] = Field(default_factory=list)
