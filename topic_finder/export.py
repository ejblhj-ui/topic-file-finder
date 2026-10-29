"""결과 목록 내보내기 (CSV / Markdown)."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Result


def _esc(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def export_results(results: list[Result], path: str | Path) -> Path:
    """확장자가 .csv 면 CSV(엑셀 호환 UTF-8 BOM), 그 외는 Markdown 표로 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["#", "제목", "저자", "연도", "출처", "DOI", "요약", "원문", "파일"])
            for i, r in enumerate(results, 1):
                w.writerow(
                    [i, r.title, "; ".join(r.authors), r.year or "", r.source, r.doi or "",
                     r.summary or "", r.url or "", r.file_url or ""]
                )
    else:
        lines = ["| # | 제목 | 연도 | 출처 | 요약 | 링크 |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(results, 1):
            link = r.url or r.file_url or ""
            lines.append(f"| {i} | {_esc(r.title)} | {r.year or ''} | {r.source} | {_esc(r.summary)} | {link} |")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
