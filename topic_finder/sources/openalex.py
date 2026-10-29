"""OpenAlex API 어댑터 (키 불필요, mailto 로 polite pool 사용)."""

from __future__ import annotations

from ..models import Result
from .base import Source, SourceError

OPENALEX_API = "https://api.openalex.org/works"


class OpenAlexSource(Source):
    name = "openalex"
    label = "OpenAlex"
    kind = "academic"
    key_env = "OPENALEX_API_KEY"  # 선택: 없어도 동작, 있으면 요청 한도 증가

    async def _search(self, query, limit, *, year_from=None, year_to=None):
        params: dict = {
            "search": query,
            "per-page": max(1, min(limit, 200)),
            "mailto": self.settings.contact_email,
        }
        if self.settings.openalex_api_key:
            params["api_key"] = self.settings.openalex_api_key
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        resp = await self._get(OPENALEX_API, params=params)
        try:
            return parse_openalex(resp.json())
        except ValueError as e:
            raise SourceError(f"openalex: 응답 파싱 실패 ({e})") from e


def reconstruct_abstract(inverted: dict | None) -> str | None:
    """OpenAlex 의 abstract_inverted_index → 원문 문자열."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


def parse_openalex(data: dict) -> list[Result]:
    out: list[Result] = []
    for w in data.get("results", []) or []:
        title = w.get("display_name") or w.get("title")
        if not title:
            continue
        oa = w.get("best_oa_location") or {}
        pdf = oa.get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
        landing = (
            oa.get("landing_page_url")
            or (w.get("primary_location") or {}).get("landing_page_url")
            or w.get("doi")
            or w.get("id")
        )
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in (w.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]
        wid = (w.get("id") or "").rsplit("/", 1)[-1] or title[:20]
        out.append(
            Result(
                id=f"openalex:{wid}",
                title=" ".join(str(title).split()),
                authors=authors,
                year=w.get("publication_year"),
                source="openalex",
                url=landing,
                file_url=pdf,
                file_type="pdf" if pdf and ".pdf" in pdf.lower() else (None if not pdf else "pdf"),
                abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
                doi=w.get("doi"),
                published_at=w.get("publication_date"),
                extra={"type": w.get("type"), "cited_by_count": w.get("cited_by_count")},
            )
        )
    return out
