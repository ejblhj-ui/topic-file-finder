"""병렬 검색 → 중복 제거 → 순위 → 요약."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Callable

import httpx

from .config import Settings, load_settings
from .models import Result, SearchOutcome, normalize_doi, normalize_title
from .sources import Source, SourceError, make_sources, resolve_names
from .summarize import claude_available, claude_summary_ko, rule_summary

log = logging.getLogger("topic_finder.search")

STOPWORDS = {
    "the", "and", "of", "for", "a", "an", "in", "on", "to", "with", "using", "based", "by", "from",
    "및", "의", "와", "과", "를", "을", "에", "에서", "대한", "관한", "위한",
}
TITLE_SIMILARITY = 0.9


def tokenize(text: str | None) -> list[str]:
    toks = re.findall(r"[0-9a-zA-Z가-힣]+", (text or "").lower())
    out = []
    for t in toks:
        if len(t) >= 2 and t not in STOPWORDS and t not in out:
            out.append(t)
    return out


# ----------------------------------------------------------------- 중복 제거


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if abs(len(a) - len(b)) / max(len(a), len(b)) > 0.15:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def merge(base: Result, other: Result) -> Result:
    """같은 자료로 판단된 두 결과를 합친다. file_url 이 있는 쪽을 우선한다."""
    m = base.model_copy(deep=True)
    if not m.file_url and other.file_url:
        m.file_url, m.file_type = other.file_url, other.file_type
    for field in ("abstract", "doi", "year", "url", "published_at"):
        if not getattr(m, field) and getattr(other, field):
            setattr(m, field, getattr(other, field))
    if not m.authors and other.authors:
        m.authors = list(other.authors)
    also = m.extra.setdefault("also_in", [])
    if other.source not in also and other.source != m.source:
        also.append(other.source)
    m.extra.setdefault("merged_ids", []).append(other.id)
    return m


def dedupe(results: list[Result]) -> list[Result]:
    merged: list[Result] = []
    by_doi: dict[str, int] = {}
    titles: list[tuple[str, int]] = []
    for r in results:
        d = normalize_doi(r.doi)
        nt = normalize_title(r.title)
        idx: int | None = None
        if d and d in by_doi:
            idx = by_doi[d]
        else:
            for t, i in titles:
                if nt == t or (len(nt) > 15 and _similar(nt, t) >= TITLE_SIMILARITY):
                    idx = i
                    break
        if idx is None:
            merged.append(r.model_copy(deep=True))
            i = len(merged) - 1
            if d:
                by_doi[d] = i
            titles.append((nt, i))
        else:
            merged[idx] = merge(merged[idx], r)
            if d:
                by_doi.setdefault(d, idx)
    return merged


# ----------------------------------------------------------------- 순위


def score(r: Result, terms: list[str], now_year: int | None = None) -> float:
    now_year = now_year or datetime.now().year
    title = r.title.lower()
    abstract = (r.abstract or "").lower()
    s = 0.0
    for t in terms:
        if t in title:
            s += 3.0
        if t in abstract:
            s += 1.0
    if r.year:
        s += max(0.0, min(2.0, (r.year - (now_year - 10)) * 0.2))
    if r.file_url:
        s += 1.5
    return round(s, 3)


def rank(results: list[Result], terms: list[str]) -> list[Result]:
    for r in results:
        r.score = score(r, terms)
    return sorted(results, key=lambda r: (-r.score, r.title.lower()))


# ----------------------------------------------------------------- 검색


async def _run(source: Source, query: str, limit: int, year_from, year_to) -> list[Result]:
    try:
        return await source.search(query, limit, year_from=year_from, year_to=year_to)
    except SourceError:
        raise
    except Exception as e:  # noqa: BLE001 — 어댑터 내부 오류도 경고로만 보고한다
        raise SourceError(f"{source.name}: {type(e).__name__}: {e}") from e


async def search_all(
    query_ko: str,
    query_en: str | None = None,
    *,
    sources: list[str] | None = None,
    limit: int = 30,
    year_from: int | None = None,
    year_to: int | None = None,
    file_types: list[str] | tuple[str, ...] | None = ("pdf",),
    settings: Settings | None = None,
    ko_summary: bool = False,
    progress: Callable[[str, int], None] | None = None,
) -> SearchOutcome:
    """모든 출처를 병렬로 검색하고 중복 제거·순위·요약까지 마친 결과를 돌려준다.

    - academic 출처에는 ``query_en`` (없으면 ``query_ko``), web 출처에는 ``query_ko`` 를 보낸다.
    - 출처 하나가 실패해도 나머지 결과는 반환하고 ``warnings`` 에 사유를 담는다.
    """
    settings = settings or load_settings()
    query_ko = " ".join((query_ko or "").split())
    query_en = " ".join((query_en or "").split()) or None
    if not query_ko:
        raise ValueError("주제(query_ko)가 비어 있습니다")
    names = resolve_names(sources or settings.default_sources)
    per = settings.per_source_limit or limit
    warnings: list[str] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.ua}, timeout=settings.timeout, follow_redirects=True
    ) as client:
        srcs, warn = make_sources(names, settings, client)
        warnings.extend(warn)
        tasks = []
        for s in srcs:
            if s.kind == "web":
                q = query_ko
                s.file_type = file_types[0] if file_types else None  # type: ignore[attr-defined]
            else:
                q = query_en or query_ko
            tasks.append(_run(s, q, per, year_from, year_to))
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[Result] = []
    used: list[str] = []
    for s, out in zip(srcs, outcomes):
        if isinstance(out, BaseException):
            warnings.append(f"{s.label}: {out}")
            log.warning("%s 실패: %s", s.name, out)
            if progress:
                progress(s.name, -1)
            continue
        used.append(s.name)
        all_results.extend(out)
        if progress:
            progress(s.name, len(out))

    results = dedupe(all_results)
    terms = tokenize(query_ko) + [t for t in tokenize(query_en) if t not in tokenize(query_ko)]
    results = rank(results, terms)[:limit]
    for r in results:
        r.summary = r.summary or rule_summary(r.abstract)
    if ko_summary and claude_available(settings):
        for r in results[:10]:
            if r.abstract:
                ko = await asyncio.to_thread(claude_summary_ko, r.title, r.abstract, settings)
                if ko:
                    r.summary = ko
    return SearchOutcome(
        query_ko=query_ko, query_en=query_en, results=results, warnings=warnings, sources_used=used
    )
