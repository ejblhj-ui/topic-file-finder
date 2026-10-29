import httpx
import respx

from conftest import ARXIV_XML, OPENALEX_JSON, S2_JSON
from topic_finder.search import search_all
from topic_finder.sources import describe_sources, resolve_names, web_ddg
from topic_finder.sources.arxiv import parse_arxiv_feed
from topic_finder.sources.openalex import reconstruct_abstract
from topic_finder.sources.web_ddg import guess_year, parse_ddg


def test_parse_arxiv_feed():
    results = parse_arxiv_feed(ARXIV_XML)
    assert [r.title for r in results] == [
        "Smart Farm Weeding Robot with Vision",
        "Crop Row Detection for Autonomous Tractors",
    ]
    first = results[0]
    assert first.id == "arxiv:2301.00001v1"
    assert first.file_url == "https://arxiv.org/pdf/2301.00001v1"
    assert first.url == "https://arxiv.org/abs/2301.00001v1"
    assert first.year == 2023 and first.published_at == "2023-01-02"
    assert first.authors == ["Kim Minsu", "Lee Jiyoung"]
    assert first.doi == "10.1000/xyz123"
    # pdf 링크가 없는 항목은 abs → pdf 로 만들어 준다
    assert results[1].file_url == "https://arxiv.org/pdf/2205.00002v2"


@respx.mock
async def test_arxiv_search(settings):
    route = respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV_XML))
    out = await search_all("스마트팜 제초 로봇", "smart farm weeding robot", sources=["arxiv"], settings=settings)
    assert route.called
    url = str(route.calls[0].request.url)
    assert "all%3Asmart+AND+all%3Afarm" in url or "all:smart AND all:farm" in url or "all%3Asmart" in url
    assert out.sources_used == ["arxiv"] and not out.warnings
    assert len(out.results) == 2
    assert out.results[0].title == "Smart Farm Weeding Robot with Vision"  # 키워드 일치로 상위
    assert out.results[0].summary.startswith("We present a weeding robot. It detects weeds. It works in fields.")


@respx.mock
async def test_arxiv_year_filter_in_query(settings):
    route = respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV_XML))
    await search_all("x", "weeding robot", sources=["arxiv"], settings=settings, year_from=2020, year_to=2024)
    assert "submittedDate" in str(route.calls[0].request.url)


@respx.mock
async def test_openalex_search(settings):
    route = respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX_JSON))
    out = await search_all("스마트팜", "smart farm weeding robot", sources=["openalex"], settings=settings)
    assert "mailto" in str(route.calls[0].request.url)
    assert len(out.results) == 2
    top = out.results[0]
    assert top.id == "openalex:W123"
    assert top.file_url == "https://files.example.com/w123.pdf"
    assert top.abstract == "We present a robot."
    assert top.doi == "https://doi.org/10.1000/XYZ123"
    assert top.key == "doi:10.1000/xyz123"
    other = out.results[1]
    assert other.file_url is None and other.url == "https://example.com/w456"


def test_reconstruct_abstract():
    assert reconstruct_abstract({"b": [1], "a": [0], "c": [2]}) == "a b c"
    assert reconstruct_abstract(None) is None


@respx.mock
async def test_semantic_scholar_search(settings):
    route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2_JSON)
    )
    out = await search_all("제초", "selective weeding", sources=["s2"], settings=settings, year_from=2020)
    assert "year=2020-" in str(route.calls[0].request.url)
    assert len(out.results) == 1
    r = out.results[0]
    assert r.id == "semantic_scholar:abc" and r.doi == "10.1000/abc"
    assert r.file_url == "https://files.example.com/abc.pdf" and r.authors == ["Lee"]


async def test_web_search(settings, monkeypatch):
    calls = {}

    def fake_ddg(query, max_results, region):
        calls.update(query=query, max_results=max_results, region=region)
        return [
            {
                "title": "스마트팜 제초 로봇 기술동향 2024",
                "href": "https://gov.example.kr/report.pdf",
                "body": "2024년 농촌진흥청 보고서",
            },
            {"title": "오래된 자료", "href": "https://old.example.kr/old.pdf", "body": "2008년 발간"},
        ]

    monkeypatch.setattr(web_ddg, "_ddg_text", fake_ddg)
    monkeypatch.setattr(web_ddg, "_has_ddgs", lambda: True)
    out = await search_all("스마트팜 제초 로봇", "smart farm", sources=["web"], settings=settings, year_from=2015)
    assert calls["query"] == "스마트팜 제초 로봇 filetype:pdf"  # 웹 출처는 한국어 주제를 쓴다
    assert calls["region"] == "kr-kr"
    assert len(out.results) == 1  # 2008년 자료는 연도 필터로 제외
    r = out.results[0]
    assert r.file_url == "https://gov.example.kr/report.pdf" and r.file_type == "pdf" and r.year == 2024
    assert r.id.startswith("web:")


def test_parse_ddg_and_guess_year():
    assert guess_year("보고서 2021년 발간 (개정 2023)") == 2023
    assert guess_year("no year here") is None
    rows = [{"title": "T", "href": "https://a.kr/x.hwp", "body": ""}, {"title": "", "href": "https://a.kr/y.pdf"}]
    out = parse_ddg(rows)
    assert len(out) == 1 and out[0].file_type == "hwp" and out[0].year is None


def test_resolve_names_and_describe(settings):
    assert resolve_names(["S2", "ddg", "arxiv", "arxiv"]) == ["semantic_scholar", "web", "arxiv"]
    info = {s["name"]: s for s in describe_sources(settings)}
    assert info["arxiv"]["available"] is True
    assert info["core"]["available"] is False and "CORE_API_KEY" in info["core"]["reason"]
