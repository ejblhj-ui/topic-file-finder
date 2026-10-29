from topic_finder.models import SearchOutcome, Topic
from topic_finder.topics import ResultsCache, SeenIndex, TopicStore


def test_topic_store_roundtrip(settings):
    store = TopicStore(settings.topics_file)
    assert store.list() == []
    store.add(Topic(name="스마트팜 제초 로봇", en="smart farm weeding robot", sources=["arxiv", "web"], limit=20))
    store.add(Topic(name="3D프린팅 교육", limit=10, year_from=2020))
    assert [t.name for t in store.list()] == ["스마트팜 제초 로봇", "3D프린팅 교육"]
    t = store.get("스마트팜 제초 로봇")
    assert t and t.en == "smart farm weeding robot" and t.sources == ["arxiv", "web"] and t.file_types == ["pdf"]
    # 같은 이름은 덮어쓴다
    store.add(Topic(name="스마트팜 제초 로봇", en="weeding robot", limit=5))
    assert len(store.list()) == 2 and store.get("스마트팜 제초 로봇").limit == 5
    assert store.remove("3D프린팅 교육") is True and store.remove("없는 주제") is False
    assert [t.name for t in store.list()] == ["스마트팜 제초 로봇"]
    # 파일이 사람이 읽을 수 있는 한글 YAML 이어야 한다
    assert "스마트팜 제초 로봇" in settings.topics_file.read_text(encoding="utf-8")


def test_seen_index_filters_new(settings, sample_results):
    seen = SeenIndex(settings.seen_db)
    assert seen.filter_new("주제", sample_results) == sample_results
    assert seen.mark("주제", sample_results[:2]) == 2
    new = seen.filter_new("주제", sample_results)
    assert [r.id for r in new] == ["web:3"]
    assert seen.count("주제") == 2 and seen.count("다른 주제") == 0
    # 같은 키를 다시 기록해도 중복되지 않는다
    seen.mark("주제", sample_results)
    assert seen.count("주제") == 3
    assert seen.clear("주제") == 3 and seen.filter_new("주제", sample_results) == sample_results


def test_seen_key_uses_doi_then_title(sample_results):
    assert sample_results[0].key == "doi:10.1000/xyz123"
    assert sample_results[1].key == "title:soilmoisturesensorsreview"
    assert sample_results[2].key == "title:스마트팜제초로봇기술동향보고서"


def test_results_cache_roundtrip(settings, sample_results):
    cache = ResultsCache(settings)
    assert cache.load("스마트팜 제초 로봇") is None
    outcome = SearchOutcome(query_ko="스마트팜 제초 로봇", query_en="smart farm", results=sample_results, sources_used=["arxiv"])
    path = cache.save("스마트팜 제초 로봇", outcome)
    assert path.name == "스마트팜-제초-로봇.json"
    loaded = cache.load("스마트팜 제초 로봇")
    assert loaded == outcome
