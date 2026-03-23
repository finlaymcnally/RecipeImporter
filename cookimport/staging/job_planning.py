from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.plugins import registry
from cookimport.staging.pdf_jobs import plan_job_ranges, plan_pdf_page_ranges


@dataclass(frozen=True)
class JobSpec:
    file_path: Path
    job_index: int
    job_count: int
    start_page: int | None = None
    end_page: int | None = None
    start_spine: int | None = None
    end_spine: int | None = None

    @property
    def has_range(self) -> bool:
        return self.range_kind is not None

    @property
    def range_kind(self) -> str | None:
        if self.start_page is not None or self.end_page is not None:
            return "pdf"
        if self.start_spine is not None or self.end_spine is not None:
            return "epub"
        return None

    @property
    def display_name(self) -> str:
        if not self.has_range:
            return self.file_path.name
        if self.range_kind == "epub":
            start = (self.start_spine or 0) + 1
            end = self.end_spine or start
            return f"{self.file_path.name} [spine {start}-{end}]"
        start = (self.start_page or 0) + 1
        end = self.end_page or start
        return f"{self.file_path.name} [pages {start}-{end}]"

    @property
    def merge_order_start(self) -> int:
        if self.start_page is not None:
            return int(self.start_page)
        if self.start_spine is not None:
            return int(self.start_spine)
        return 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "job_index": self.job_index,
            "job_count": self.job_count,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "start_spine": self.start_spine,
            "end_spine": self.end_spine,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> JobSpec:
        return cls(
            file_path=Path(str(payload.get("file_path") or "")).expanduser(),
            job_index=int(payload.get("job_index") or 0),
            job_count=max(1, int(payload.get("job_count") or 1)),
            start_page=_coerce_optional_int(payload.get("start_page")),
            end_page=_coerce_optional_int(payload.get("end_page")),
            start_spine=_coerce_optional_int(payload.get("start_spine")),
            end_spine=_coerce_optional_int(payload.get("end_spine")),
        )


def resolve_pdf_page_count(path: Path) -> int | None:
    importer = registry.get_importer("pdf")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    page_count = inspection.sheets[0].page_count
    return _coerce_optional_int(page_count)


def resolve_epub_spine_count(path: Path) -> int | None:
    importer = registry.get_importer("epub")
    if importer is None:
        return None
    try:
        inspection = importer.inspect(path)
    except Exception:
        return None
    if not inspection.sheets:
        return None
    spine_count = inspection.sheets[0].spine_count
    return _coerce_optional_int(spine_count)


def plan_source_jobs(
    files: Sequence[Path],
    *,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    epub_extractor: str = "unstructured",
    epub_extractor_by_file: Mapping[Path, str] | None = None,
) -> list[JobSpec]:
    jobs: list[JobSpec] = []
    for file_path in files:
        jobs.extend(
            plan_source_job(
                file_path,
                pdf_pages_per_job=pdf_pages_per_job,
                epub_spine_items_per_job=epub_spine_items_per_job,
                pdf_split_workers=pdf_split_workers,
                epub_split_workers=epub_split_workers,
                epub_extractor=epub_extractor,
                selected_epub_extractor=(epub_extractor_by_file or {}).get(file_path),
            )
        )
    return jobs


def plan_source_job(
    file_path: Path,
    *,
    pdf_pages_per_job: int,
    epub_spine_items_per_job: int,
    pdf_split_workers: int,
    epub_split_workers: int,
    epub_extractor: str = "unstructured",
    selected_epub_extractor: str | None = None,
) -> list[JobSpec]:
    effective_epub_extractor = str(
        selected_epub_extractor if selected_epub_extractor is not None else epub_extractor
    ).strip().lower()

    if (
        pdf_split_workers > 1
        and file_path.suffix.lower() == ".pdf"
        and pdf_pages_per_job > 0
    ):
        page_count = resolve_pdf_page_count(file_path)
        if page_count:
            ranges = plan_pdf_page_ranges(
                page_count,
                pdf_split_workers,
                pdf_pages_per_job,
            )
            if len(ranges) > 1:
                return [
                    JobSpec(
                        file_path=file_path,
                        job_index=idx,
                        job_count=len(ranges),
                        start_page=start,
                        end_page=end,
                    )
                    for idx, (start, end) in enumerate(ranges)
                ]

    if (
        epub_split_workers > 1
        and file_path.suffix.lower() == ".epub"
        and effective_epub_extractor != "markitdown"
        and epub_spine_items_per_job > 0
    ):
        spine_count = resolve_epub_spine_count(file_path)
        if spine_count:
            ranges = plan_job_ranges(
                spine_count,
                epub_split_workers,
                epub_spine_items_per_job,
            )
            if len(ranges) > 1:
                return [
                    JobSpec(
                        file_path=file_path,
                        job_index=idx,
                        job_count=len(ranges),
                        start_spine=start,
                        end_spine=end,
                    )
                    for idx, (start, end) in enumerate(ranges)
                ]

    return [JobSpec(file_path=file_path, job_index=0, job_count=1)]


def compute_effective_workers_for_sources(
    *,
    workers: int,
    epub_split_workers: int,
    epub_extractor: str = "unstructured",
    file_paths: Sequence[Path] | None = None,
    all_epub: bool | None = None,
) -> int:
    effective_all_epub = bool(all_epub)
    if all_epub is None and file_paths is not None:
        effective_all_epub = bool(file_paths) and all(
            path.suffix.lower() == ".epub" for path in file_paths
        )
    selected_extractor = str(epub_extractor or "").strip().lower()
    if (
        effective_all_epub
        and selected_extractor != "markitdown"
        and epub_split_workers > workers
    ):
        return epub_split_workers
    return workers


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
