"""데이터 모델: 검색 결과, 주제, 검색 결과 묶음."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

_DOI_PREFIX = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.IGNORECASE)
_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")


def normalize_doi(doi: str | None) -> str | None:
    """DOI를 비교용으로 정규화한다 (URL 접두어·'doi:' 제거, 소문자)."""
    if not doi:
        return None
    d = _DOI_PREFIX.sub("", doi.strip()).lower()
    d = d.removeprefix("doi:").strip()
    return d or None


def normalize_title(title: str) -> str:
    """제목을 비교용으로 정규화한다 (소문자, 기호·공백 제거)."""
    return _NON_WORD.sub("", (title or "").lower())


class Result(BaseModel):
    """출처 어댑터가 반환하는 검색 결과 한 건."""

    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    source: str
    url: str | None = None  # 랜딩 페이지
    file_url: str | None = None  # 직접 파일 링크 (없을 수 있음)
    file_type: str | None = None  # pdf 등
    abstract: str | None = None
    doi: str | None = None
    published_at: str | None = None  # YYYY-MM-DD
    extra: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    summary: str | None = None

    @property
    def key(self) -> str:
        """중복 제거·seen 인덱스에 쓰는 안정적인 키 (DOI 우선, 없으면 정규화 제목)."""
        d = normalize_doi(self.doi)
        return f"doi:{d}" if d else f"title:{normalize_title(self.title)}"

    @property
    def has_file(self) -> bool:
        return bool(self.file_url)


class Topic(BaseModel):
    """저장된 주제 설정 (topics.yaml 한 항목)."""

    name: str
    en: str | None = None
    sources: list[str] | None = None
    limit: int = 30
    year_from: int | None = None
    year_to: int | None = None
    file_types: list[str] = Field(default_factory=lambda: ["pdf"])


class SearchOutcome(BaseModel):
    """한 번의 검색 결과 묶음."""

    query_ko: str
    query_en: str | None = None
    results: list[Result] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
