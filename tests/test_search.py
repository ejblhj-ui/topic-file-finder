import httpx
import respx

from conftest import ARXIV_XML, OPENALEX_JSON, make_result
from topic_finder.search import dedupe, rank, search_all, tokenize
from topic_finder.summarize import rule_summary


def test_tokenize_drops_stopwords_and_short():
    assert tokenize("Smart farm weeding robot with vision") == ["smart", "farm", "weeding", "robot", "vision"]
    assert tokenize("스마트팜 제초 로봇의 동향") == ["스마트팜", "제초", "로봇의", "동향"]


def test_dedupe_by_doi_prefers_file_url():
    a = make_result(id="a", title="Title A", doi="10.1000/ABC", source="arxiv", abstract=None)
    b = make_result(
        id="b", title="Completely different title", doi="https://doi.org/10.1000/abc", source="openalex",
        file_url="https://f/x.pdf", file_type="pdf", abstract="Filled in.",
    )
    m = dedupe([a, b])
    assert len(m) == 1
    assert m[0].file_url == "https://f/x.pdf" and m[0].abstract == "Filled in."
    assert m[0].extra["also_in"] == ["openalex"] and m[0].extra["merged_ids"] == ["b"]


def test_dedupe_by_similar_title():
    a = make_result(id="a", title="Smart farm weeding robot with vision", source="arxiv")
    b = make_result(id="b", title="Smart Farm Weeding Robot with Vision.", source="semantic_scholar")
    c = make_result(id="c", title="Smart farm weeding robot: a survey of twenty years", source="openalex")
    m = dedupe([a, b, c])
    assert [r.id for r in m] == ["a", "c"]


def test_dedupe_short_titles_need_exact_match():
    a = make_result(id="a", title="Robot survey", source="arxiv")
    b = make_result(id="b", title="Robot survey2", source="openalex")
    assert len(dedupe([a, b])) == 2


def test_rank_prefers_keyword_recency_and_file():
    hit = make_result(id="h", title="Weeding robot for smart farm", year=2024, file_url="https://f/h.pdf")
    miss = make_result(id="m", title="Something else", year=2010)
    mid = make_result(id="k", title="Weeding robot", year=2015)
    ranked = rank([miss, mid, hit], ["weeding", "robot", "smart", "farm"])
    assert [r.id for r in ranked] == ["h", "k", "m"]
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_rule_summary():
    s = rule_summary("One. Two. Three. Four.", max_sentences=3)
    assert s == "One. Two. Three."
    assert rule_summary("로봇을 만든다. 잡초를 인식한다. 제초한다. 끝.", max_sentences=2) == "로봇을 만든다. 잡초를 인식한다."
    assert rule_summary(None) is None
    assert len(rule_summary("x" * 1000, max_chars=100)) == 100


@respx.mock
async def test_failed_source_is_isolated(settings):
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(500))
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX_JSON))
    out = await search_all("스마트팜", "smart farm", sources=["arxiv", "openalex"], settings=settings)
    assert out.sources_used == ["openalex"]
    assert len(out.results) == 2
    assert any("arXiv" in w and "500" in w for w in out.warnings)


@respx.mock
async def test_cross_source_dedupe_and_limit(settings):
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV_XML))
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX_JSON))
    out = await search_all("스마트팜", "smart farm weeding robot", sources=["arxiv", "openalex"], settings=settings)
    # arXiv 의 10.1000/xyz123 와 OpenAlex 의 10.1000/XYZ123 는 같은 자료
    assert len(out.results) == 3
    top = out.results[0]
    assert top.title == "Smart Farm Weeding Robot with Vision"
    assert "openalex" in top.extra.get("also_in", [])
    limited = await search_all("스마트팜", "smart farm", sources=["arxiv", "openalex"], settings=settings, limit=2)
    assert len(limited.results) == 2


async def test_unknown_source_warning(settings):
    out = await search_all("스마트팜", None, sources=["nope"], settings=settings)
    assert out.results == [] and any("알 수 없는 출처" in w for w in out.warnings)


async def test_stub_source_reports_missing_key(settings):
    out = await search_all("스마트팜", None, sources=["core"], settings=settings)
    assert any("CORE_API_KEY" in w for w in out.warnings)
