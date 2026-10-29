"""DuckDuckGo 웹 검색 어댑터 — 일반 웹의 PDF(보고서·정부 자료 등). `ddgs` 패키지 사용, 키 불필요."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit

from ..models import Result
from .base import Source, SourceError, SourceUnavailable

HANGUL = re.compile(r"[가-힣]")
YEAR = re.compile(r"(?<!\d)(19[6-9]\d|20\d{2})(?!\d)")
FILE_EXT = re.compile(r"\.(pdf|hwp|hwpx|docx?|pptx?|xlsx?|zip|txt|csv)$", re.IGNORECASE)


def _ddg_text(query: str, max_results: int, region: str) -> list[dict]:
    """실제 DuckDuckGo 호출. 테스트에서는 이 함수를 monkeypatch 한다."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise SourceUnavailable("web: `pip install ddgs` 가 필요합니다") from e
    with DDGS() as ddgs:
        return list(ddgs.text(query, region=region, max_results=max_results) or [])


def _has_ddgs() -> bool:
    try:
        import ddgs  # noqa: F401

        return True
    except ImportError:
        try:
            import duckduckgo_search  # noqa: F401

            return True
        except ImportError:
            return False


class WebSource(Source):
    name = "web"
    label = "웹 검색 (DuckDuckGo · PDF)"
    kind = "web"
    file_type: str | None = "pdf"  # search_all 이 파일 유형 필터에 맞춰 바꿔 준다

    def available(self):
        if not _has_ddgs():
            return False, "`pip install ddgs` 필요"
        return True, ""

    async def _search(self, query, limit, *, year_from=None, year_to=None):
        if not _has_ddgs():
            raise SourceUnavailable("web: `pip install ddgs` 가 필요합니다")
        q = f"{query} filetype:{self.file_type}" if self.file_type else query
        region = self.settings.web_region
        if region == "auto":
            region = "kr-kr" if HANGUL.search(query) else "wt-wt"
        try:
            rows = await asyncio.to_thread(_ddg_text, q, max(1, limit), region)
        except SourceUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 — ddgs 는 백엔드마다 다른 예외를 낸다
            msg = str(e)
            if "No results" in msg:
                raise SourceError(
                    "web: 결과 없음 — 검색 엔진이 이 네트워크의 요청을 거부했을 수 있습니다 (잠시 후 또는 다른 네트워크에서 재시도)"
                ) from e
            raise SourceError(f"web: 검색 엔진 요청 실패 ({type(e).__name__}: {msg[:120]})") from e
        return parse_ddg(rows, year_from=year_from, year_to=year_to, file_type=self.file_type)


def guess_year(text: str) -> int | None:
    """제목·스니펫에서 그럴듯한 연도를 추출한다 (가장 최근 값, 내년 이후는 제외)."""
    this_year = datetime.now().year
    years = [int(y) for y in YEAR.findall(text or "") if int(y) <= this_year + 1]
    return max(years) if years else None


def parse_ddg(rows: list[dict], *, year_from=None, year_to=None, file_type: str | None = "pdf") -> list[Result]:
    out: list[Result] = []
    for row in rows or []:
        href = (row.get("href") or row.get("url") or "").strip()
        title = " ".join((row.get("title") or "").split())
        if not href or not title:
            continue
        body = " ".join((row.get("body") or "").split())
        year = guess_year(f"{title} {body}")
        if year is not None and ((year_from and year < year_from) or (year_to and year > year_to)):
            continue
        path = urlsplit(href).path
        m = FILE_EXT.search(path)
        ext = m.group(1).lower() if m else (file_type or None)
        out.append(
            Result(
                id=f"web:{hashlib.sha1(href.encode('utf-8')).hexdigest()[:12]}",
                title=title,
                source="web",
                year=year,
                url=href,
                file_url=href,  # filetype 검색이므로 직접 파일로 가정 — 다운로더가 HTML 이면 걸러낸다
                file_type=ext,
                abstract=body or None,
                extra={"domain": urlsplit(href).netloc},
            )
        )
    return out
