"""Configuration loader — reads config.yaml and merges with environment variable overrides.

Adapted from: https://github.com/mohitagr18/timesheet-ocr/blob/main/src/config.py

Resolution order:
    1. Pydantic model defaults
    2. config.yaml values
    3. Environment variable overrides (DOCBENCH_<SECTION>_<KEY>=value)

Example override:
    DOCBENCH_EVALUATION_HOURS_TOLERANCE_MINUTES=30
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    input_dir: str = "input"
    output_dir: str = "output"
    ground_truth_file: str = "input/ground_truth.xlsx"


class EvaluationConfig(BaseModel):
    hours_tolerance_minutes: int = 15
    time_tolerance_minutes: int = 30
    review_borderline_hours: bool = True
    review_flagged_matching_gt: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    per_method_log: bool = True


class CacheConfig(BaseModel):
    enabled: bool = True


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    # Resolved at load time; not in YAML
    project_root: Path = Field(default_factory=Path.cwd)

    @property
    def input_path(self) -> Path:
        return self.project_root / self.paths.input_dir

    @property
    def output_path(self) -> Path:
        return self.project_root / self.paths.output_dir

    @property
    def ground_truth_path(self) -> Path:
        return self.project_root / self.paths.ground_truth_file


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load AppConfig from YAML with optional environment variable overrides."""
    project_root = _find_project_root()

    if config_path is None:
        config_path = project_root / "config.yaml"
    else:
        config_path = Path(config_path)

    data: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    _apply_env_overrides(data)

    config = AppConfig(**data, project_root=project_root)
    config.output_path.mkdir(parents=True, exist_ok=True)
    return config


def _find_project_root() -> Path:
    """Walk upward from cwd to find pyproject.toml as the project root marker."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return current


def _apply_env_overrides(data: dict[str, Any]) -> None:
    """Override config values from DOCBENCH_<SECTION>_<KEY> environment variables."""
    prefix = "DOCBENCH_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, field = parts
        if section not in data:
            data[section] = {}
        try:
            data[section][field] = int(value)
        except ValueError:
            try:
                data[section][field] = float(value)
            except ValueError:
                if value.lower() in ("true", "false"):
                    data[section][field] = value.lower() == "true"
                else:
                    data[section][field] = value
