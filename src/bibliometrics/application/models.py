from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union


PathLike = Union[str, Path]
ProgressCallback = Optional[Callable[[str, float], None]]
YEAR_RANGE_PATTERN = re.compile(r"^(\d{4})-(\d{4})$")
DEFAULT_CLEANING_CONFIG = "config/institution_cleaning_rules_ultimate.json"


@dataclass(slots=True)
class WorkflowOptions:
    """User-facing workflow configuration."""

    data_dir: PathLike
    language: str = "English"
    enable_ai: bool = True
    enable_cleaning: bool = True
    cleaning_config: str = DEFAULT_CLEANING_CONFIG
    year_range: Optional[str] = None
    enable_plot: bool = True
    progress_callback: ProgressCallback = None

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    @property
    def has_year_filter(self) -> bool:
        return bool(self.year_range)

    def parse_year_range(self) -> Optional[tuple[int, int]]:
        if not self.year_range:
            return None

        match = YEAR_RANGE_PATTERN.match(self.year_range)
        if not match:
            raise ValueError(
                f"年份范围格式错误: {self.year_range}，应为 YYYY-YYYY 格式（如 2015-2024）"
            )

        min_year = int(match.group(1))
        max_year = int(match.group(2))
        if min_year > max_year:
            raise ValueError(f"最小年份 ({min_year}) 不能大于最大年份 ({max_year})")

        return min_year, max_year

    def build_paths(self) -> "WorkflowPaths":
        return WorkflowPaths.for_data_dir(self.data_dir, self.language)


@dataclass(frozen=True, slots=True)
class WorkflowPaths:
    """Canonical artifact paths for a workflow run."""

    data_dir: Path
    wos_file: Path
    scopus_file: Path
    wos_year_filtered: Path
    scopus_year_filtered: Path
    scopus_converted: Path
    scopus_enriched: Path
    merged_file: Path
    filtered_file: Path
    cleaned_file: Path
    report_file: Path

    @classmethod
    def for_data_dir(cls, data_dir: PathLike, language: str) -> "WorkflowPaths":
        base_dir = Path(data_dir)
        return cls(
            data_dir=base_dir,
            wos_file=base_dir / "wos.txt",
            scopus_file=base_dir / "scopus.csv",
            wos_year_filtered=base_dir / "wos_year_filtered.txt",
            scopus_year_filtered=base_dir / "scopus_year_filtered.csv",
            scopus_converted=base_dir / "scopus_converted_to_wos.txt",
            scopus_enriched=base_dir / "scopus_enriched.txt",
            merged_file=base_dir / "merged_deduplicated.txt",
            filtered_file=base_dir / f"{language.lower()}_only.txt",
            cleaned_file=base_dir / "Final_Version.txt",
            report_file=base_dir / "ai_workflow_report.txt",
        )

    def final_analysis_file(self, enable_cleaning: bool) -> Path:
        return self.cleaned_file if enable_cleaning else self.filtered_file


@dataclass(slots=True)
class StepRecord:
    """Normalized workflow step result used by reporting and tests."""

    step: int
    name: str
    status: str
    output: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "step": self.step,
            "name": self.name,
            "status": self.status,
        }
        if self.output is not None:
            payload["output"] = self.output
        if self.error is not None:
            payload["error"] = self.error
        payload.update(self.details)
        return payload
