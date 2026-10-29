"""Semantic Scholar Graph API 어댑터 (키 없이 저속 사용, 키가 있으면 x-api-key 헤더)."""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError

S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,abstract,externalIds,openAccessPdf,url,publicationDate,venue"


class SemanticScholarSource(Source):
    name = "semantic_scholar"
    label = "Semantic Scholar"
    kind = "academic"
    key_env = "SEMANTIC_SCHOLAR_API_KEY"  # 선택: 없어도 동작, 있으면 요청 한도 증가

    async def _search(self, query, limit, *, year_from=None, year_to=None):
        params: dict = {"query": query, "limit": max(1, min(limit, 100)), "fields": FIELDS}
        if year_from or year_to:
            params["year"] = f"{year_from or ''}-{year_to or ''}"
        headers = {}
        if self.settings.semantic_scholar_api_key:
            headers["x-api-key"] = self.settings.semantic_scholar_api_key
        resp = await self._get(S2_API, params=params, headers=headers)
        try:
            return parse_s2(resp.json())
        except ValueError as e:
            raise SourceError(f"semantic_scholar: 응답 파싱 실패 ({e})") from e


def parse_s2(data: dict) -> list[Result]:
    out: list[Result] = []
    for p in data.get("data", []) or []:
        title = p.get("title")
        if not title:
            continue
        pdf = (p.get("openAccessPdf") or {}).get("url")
        doi = (p.get("externalIds") or {}).get("DOI")
        pid = p.get("paperId") or title[:20]
        out.append(
            Result(
                id=f"semantic_scholar:{pid}",
                title=" ".join(str(title).split()),
                authors=[a.get("name") for a in (p.get("authors") or []) if a.get("name")],
                year=p.get("year"),
                source="semantic_scholar",
                url=p.get("url"),
                file_url=pdf,
                file_type="pdf" if pdf else None,
                abstract=p.get("abstract"),
                doi=doi,
                published_at=p.get("publicationDate"),
                extra={"venue": p.get("venue")},
            )
        )
    return out
