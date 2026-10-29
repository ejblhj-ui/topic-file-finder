"""다운로드: 주제별 폴더 저장, sha256 중복 건너뜀, manifest.json, REPORT.md."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .models import Result

log = logging.getLogger("topic_finder.download")

STATUS_KO = {
    "ok": "저장",
    "skipped_duplicate": "중복 건너뜀",
    "skipped_too_large": "크기 초과",
    "no_file_url": "링크 없음",
    "failed": "실패",
}

EXT_BY_CT = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/x-hwp": "hwp",
    "application/haansofthwp": "hwp",
    "application/vnd.hancom.hwp": "hwp",
    "application/vnd.hancom.hwpx": "hwpx",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/json": "json",
}
HTML_CT = ("text/html", "application/xhtml+xml")
RETRY_STATUS = {429, 500, 502, 503, 504}


class _Retryable(Exception):
    pass


@dataclass
class DownloadEntry:
    result: Result
    status: str  # ok | skipped_duplicate | skipped_too_large | no_file_url | failed
    reason: str = ""
    path: str | None = None
    sha256: str | None = None
    bytes: int = 0


@dataclass
class DownloadReport:
    topic: str
    out_dir: Path
    started_at: str
    entries: list[DownloadEntry] = field(default_factory=list)

    def counts(self) -> Counter:
        return Counter(e.status for e in self.entries)

    @property
    def sources(self) -> list[str]:
        return sorted({e.result.source for e in self.entries})

    @property
    def saved(self) -> list[DownloadEntry]:
        return [e for e in self.entries if e.status == "ok"]


# ----------------------------------------------------------------- 이름 규칙


def slugify(text: str) -> str:
    """'스마트팜 제초 로봇' → '스마트팜-제초-로봇' (한글 유지, 폴더 이름에 안전)."""
    t = re.sub(r"\s+", "-", (text or "").strip())
    t = re.sub(r"[^\w\-]", "", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_")
    return t or "topic"


def safe_filename(result: Result, ext: str) -> str:
    """<연도>_<제목 앞 40자>_<출처>.<확장자> — OS 에 안전한 문자만."""
    title = re.sub(r"[^\w\s\-]", "", result.title)[:40].strip()
    title = re.sub(r"\s+", "_", title) or "untitled"
    return f"{result.year or 'nd'}_{title}_{result.source}.{ext}"


def ext_from(result: Result, content_type: str | None) -> str | None:
    """Content-Type 으로 확장자를 보정한다. HTML 이면 None (직접 파일이 아님)."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in EXT_BY_CT:
        return EXT_BY_CT[ct]
    if ct.startswith(HTML_CT):
        return None
    path = urlsplit(result.file_url or "").path.lower()
    m = re.search(r"\.([a-z0-9]{2,5})$", path)
    if m:
        return m.group(1)
    return result.file_type or "bin"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("파일 이름을 만들 수 없습니다")  # pragma: no cover


def existing_hashes(topic_dir: Path) -> dict[str, str]:
    """주제 폴더의 이전 manifest 들에서 sha256 → 경로 사전을 만든다."""
    known: dict[str, str] = {}
    if not topic_dir.exists():
        return known
    for manifest in sorted(topic_dir.glob("*/manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for e in data.get("entries", []):
            if e.get("status") == "ok" and e.get("sha256"):
                known[e["sha256"]] = e.get("path") or str(manifest.parent)
    return known


# ----------------------------------------------------------------- 다운로드


async def _fetch(
    client: httpx.AsyncClient, r: Result, out_dir: Path, known: dict[str, str], settings: Settings
) -> DownloadEntry:
    max_bytes = settings.max_file_mb * 1024 * 1024
    async with client.stream("GET", r.file_url) as resp:  # type: ignore[arg-type]
        if resp.status_code in RETRY_STATUS:
            raise _Retryable(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            hint = {404: "파일 없음", 403: "접근 거부", 401: "로그인 필요", 410: "삭제됨"}.get(resp.status_code, "")
            return DownloadEntry(r, "failed", f"HTTP {resp.status_code}" + (f" ({hint})" if hint else ""))
        ext = ext_from(r, resp.headers.get("content-type"))
        if ext is None:
            return DownloadEntry(r, "failed", "HTML 페이지 (직접 파일 링크가 아님)")
        cl = resp.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > max_bytes:
            return DownloadEntry(r, "skipped_too_large", f"{int(cl) / 1e6:.0f}MB > 상한 {settings.max_file_mb}MB")
        tmp = out_dir / (safe_filename(r, ext) + ".part")
        h = hashlib.sha256()
        size = 0
        with tmp.open("wb") as f:
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    return DownloadEntry(r, "skipped_too_large", f"상한 {settings.max_file_mb}MB 초과")
                h.update(chunk)
                f.write(chunk)
    digest = h.hexdigest()
    if digest in known:
        tmp.unlink(missing_ok=True)
        return DownloadEntry(r, "skipped_duplicate", f"같은 파일이 이미 있음: {known[digest]}", sha256=digest)
    final = unique_path(out_dir / safe_filename(r, ext))
    tmp.rename(final)
    known[digest] = str(final)
    return DownloadEntry(r, "ok", path=str(final), sha256=digest, bytes=size)


async def _one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    r: Result,
    out_dir: Path,
    known: dict[str, str],
    settings: Settings,
) -> DownloadEntry:
    if not r.file_url:
        return DownloadEntry(r, "no_file_url", "직접 파일 링크 없음")
    async with sem:
        for attempt in range(settings.retries + 1):
            try:
                return await _fetch(client, r, out_dir, known, settings)
            except (_Retryable, httpx.TransportError) as e:
                if attempt >= settings.retries:
                    return DownloadEntry(r, "failed", f"{e} (재시도 {settings.retries}회 후 포기)")
                log.warning("%s 재시도 %d/%d: %s", r.file_url, attempt + 1, settings.retries, e)
                await asyncio.sleep(1.5 * (2**attempt))
            except Exception as e:  # noqa: BLE001
                return DownloadEntry(r, "failed", f"{type(e).__name__}: {e}")
    return DownloadEntry(r, "failed", "알 수 없는 오류")  # pragma: no cover


async def download_results(
    results: list[Result],
    topic: str,
    settings: Settings,
    *,
    progress: Callable[[int, int, DownloadEntry], None] | None = None,
    date: str | None = None,
) -> DownloadReport:
    """선택한 결과를 ``downloads/<주제-슬러그>/<YYYY-MM-DD>/`` 에 받고 manifest·REPORT 를 쓴다."""
    topic_dir = Path(settings.download_dir) / slugify(topic)
    out_dir = topic_dir / (date or datetime.now().strftime("%Y-%m-%d"))
    out_dir.mkdir(parents=True, exist_ok=True)
    known = existing_hashes(topic_dir)
    report = DownloadReport(topic=topic, out_dir=out_dir, started_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
    sem = asyncio.Semaphore(max(1, settings.concurrency))
    total = len(results)
    done = 0

    async def run(r: Result) -> DownloadEntry:
        nonlocal done
        entry = await _one(client, sem, r, out_dir, known, settings)
        done += 1
        if progress:
            progress(done, total, entry)
        return entry

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.ua}, timeout=settings.timeout, follow_redirects=True
    ) as client:
        entries = await asyncio.gather(*(run(r) for r in results))
    # 입력 순서를 유지한다
    report.entries = list(entries)
    write_manifest(report)
    write_report_md(report)
    return report


# ----------------------------------------------------------------- manifest / REPORT


def write_manifest(report: DownloadReport) -> Path:
    data = {
        "topic": report.topic,
        "slug": slugify(report.topic),
        "date": report.out_dir.name,
        "created_at": report.started_at,
        "out_dir": str(report.out_dir),
        "sources": report.sources,
        "counts": dict(report.counts()),
        "entries": [
            {
                **e.result.model_dump(),
                "status": e.status,
                "reason": e.reason,
                "path": e.path,
                "sha256": e.sha256,
                "bytes": e.bytes,
            }
            for e in report.entries
        ],
    }
    path = report.out_dir / "manifest.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _esc(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def _link(r: Result) -> str:
    url = r.url or r.file_url
    return f"[원문]({url})" if url else ""


def write_report_md(report: DownloadReport) -> Path:
    c = report.counts()
    ok = report.saved
    others = [e for e in report.entries if e.status != "ok"]
    lines = [
        f"# 자료 수집 리포트 — {report.topic}",
        "",
        f"- 실행 일시: {report.started_at}",
        f"- 저장 폴더: `{report.out_dir}`",
        f"- 출처: {', '.join(report.sources) or '-'}",
        f"- 결과: 총 {len(report.entries)}건 — 저장 {c['ok']} / 중복 건너뜀 {c['skipped_duplicate']} / "
        f"링크 없음 {c['no_file_url']} / 실패 {c['failed'] + c['skipped_too_large']}",
        "",
        "## 요약",
        "",
    ]
    if ok:
        for e in ok:
            r = e.result
            lines.append(f"- **{_esc(r.title)}** ({r.year or '연도 미상'}, {r.source}) — {_esc(r.summary)}")
    else:
        lines.append("(저장된 자료 없음)")
    lines += [
        "",
        "## 저장한 자료",
        "",
        "| # | 제목 | 연도 | 출처 | 요약 | 파일 | 원문 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, e in enumerate(ok, 1):
        r = e.result
        lines.append(
            f"| {i} | {_esc(r.title)} | {r.year or ''} | {r.source} | {_esc(r.summary)} | "
            f"`{Path(e.path).name if e.path else ''}` | {_link(r)} |"
        )
    if others:
        lines += ["", "## 실패·건너뜀", "", "| 제목 | 상태 | 사유 | 원문 |", "|---|---|---|---|"]
        for e in others:
            lines.append(
                f"| {_esc(e.result.title)} | {STATUS_KO.get(e.status, e.status)} | {_esc(e.reason)} | {_link(e.result)} |"
            )
    path = report.out_dir / "REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
