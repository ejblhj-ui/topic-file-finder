"""arXiv API 어댑터 (키 불필요, Atom XML)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..models import Result
from .base import Source, SourceError

ARXIV_API = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSource(Source):
    name = "arxiv"
    label = "arXiv"
    kind = "academic"

    MIN_AND_RESULTS = 8  # AND 검색 결과가 이보다 적으면 OR 검색으로 보충한다

    async def _search(self, query, limit, *, year_from=None, year_to=None):
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        date_clause = ""
        if year_from or year_to:
            start = f"{year_from or 1991}01010000"
            end = f"{year_to or 2099}12312359"
            date_clause = f" AND submittedDate:[{start} TO {end}]"
        and_q = " AND ".join(f"all:{t}" for t in terms) if terms else "all:*"
        results = await self._query(f"({and_q}){date_clause}", limit)
        # 모든 단어를 포함한 논문이 적으면, 일부 단어만 맞는 논문도 relevance 순으로 보충한다
        if len(terms) > 1 and len(results) < min(limit, self.MIN_AND_RESULTS):
            or_q = " OR ".join(f"all:{t}" for t in terms)
            seen = {r.id for r in results}
            await self.limiter.wait()
            for r in await self._query(f"({or_q}){date_clause}", limit):
                if r.id not in seen:
                    results.append(r)
                    seen.add(r.id)
        return results[:limit]

    async def _query(self, search_query: str, limit: int) -> list[Result]:
        resp = await self._get(
            ARXIV_API,
            params={
                "search_query": search_query,
                "start": 0,
                "max_results": max(1, min(limit, 200)),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
        )
        try:
            return parse_arxiv_feed(resp.text)
        except ET.ParseError as e:
            raise SourceError(f"arxiv: 응답 파싱 실패 ({e})") from e


def _text(entry: ET.Element, tag: str) -> str:
    return " ".join((entry.findtext(tag, default="", namespaces=NS) or "").split())


def parse_arxiv_feed(xml_text: str) -> list[Result]:
    root = ET.fromstring(xml_text)
    out: list[Result] = []
    for entry in root.findall("atom:entry", NS):
        title = _text(entry, "atom:title")
        if not title:
            continue
        aid = _text(entry, "atom:id")
        published = _text(entry, "atom:published")
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            " ".join((a.findtext("atom:name", default="", namespaces=NS) or "").split())
            for a in entry.findall("atom:author", NS)
        ]
        doi = entry.findtext("arxiv:doi", default=None, namespaces=NS)
        pdf, html = None, aid or None
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf = link.get("href")
            elif link.get("rel") == "alternate":
                html = link.get("href")
        if not pdf and aid:
            pdf = aid.replace("/abs/", "/pdf/")
        if pdf:
            pdf = pdf.replace("http://", "https://")
        if html:
            html = html.replace("http://", "https://")
        short = aid.rsplit("/", 1)[-1] if aid else title[:20]
        out.append(
            Result(
                id=f"arxiv:{short}",
                title=title,
                authors=[a for a in authors if a],
                year=year,
                source="arxiv",
                url=html,
                file_url=pdf,
                file_type="pdf" if pdf else None,
                abstract=_text(entry, "atom:summary") or None,
                doi=doi.strip() if doi else None,
                published_at=published[:10] or None,
                extra={"arxiv_id": short},
            )
        )
    return out
