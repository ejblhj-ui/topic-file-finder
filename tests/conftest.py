import pytest

from topic_finder.config import Settings
from topic_finder.models import Result


@pytest.fixture
def settings(tmp_path) -> Settings:
    """모든 경로를 임시 폴더로, 재시도·속도 제한은 끈 설정."""
    return Settings(
        download_dir=tmp_path / "downloads",
        data_dir=tmp_path / ".finder",
        topics_file=tmp_path / "topics.yaml",
        seen_db=tmp_path / "seen.sqlite",
        log_file=tmp_path / "logs" / "finder.log",
        retries=0,
        rate_limits={"arxiv": 1000, "openalex": 1000, "semantic_scholar": 1000, "web": 1000},
        timeout=5,
    )


def make_result(**kw) -> Result:
    base = dict(id="x:1", title="Sample", source="arxiv")
    base.update(kw)
    return Result(**base)


@pytest.fixture
def sample_results() -> list[Result]:
    return [
        make_result(
            id="arxiv:1",
            title="Smart Farm Weeding Robot with Vision",
            year=2023,
            abstract="We present a weeding robot. It detects weeds. It works in fields. Extra sentence.",
            doi="10.1000/xyz123",
            file_url="https://files.example.com/a.pdf",
            file_type="pdf",
            url="https://arxiv.org/abs/1",
        ),
        make_result(
            id="openalex:W2",
            title="Soil moisture sensors review",
            year=2019,
            source="openalex",
            abstract="A review.",
            url="https://example.com/w2",
        ),
        make_result(
            id="web:3",
            title="스마트팜 제초 로봇 기술 동향 보고서",
            year=2024,
            source="web",
            file_url="https://files.example.com/report.pdf",
            url="https://files.example.com/report.pdf",
            file_type="pdf",
        ),
    ]


ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Smart Farm Weeding Robot
      with Vision</title>
    <summary>We present a weeding robot. It detects weeds. It works in fields. More text here.</summary>
    <author><name>Kim Minsu</name></author>
    <author><name>Lee Jiyoung</name></author>
    <published>2023-01-02T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2301.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf"/>
    <arxiv:doi>10.1000/xyz123</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2205.00002v2</id>
    <title>Crop Row Detection for Autonomous Tractors</title>
    <summary>Row detection. Deep learning.</summary>
    <author><name>Park Sora</name></author>
    <published>2022-05-10T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2205.00002v2" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/XYZ123",
            "display_name": "Smart farm weeding robot with vision",
            "publication_year": 2023,
            "publication_date": "2023-01-02",
            "authorships": [{"author": {"display_name": "Kim Minsu"}}],
            "best_oa_location": {
                "pdf_url": "https://files.example.com/w123.pdf",
                "landing_page_url": "https://example.com/w123",
            },
            "abstract_inverted_index": {"We": [0], "present": [1], "a": [2], "robot.": [3]},
            "type": "article",
            "cited_by_count": 5,
        },
        {
            "id": "https://openalex.org/W456",
            "doi": None,
            "display_name": "Greenhouse climate control survey",
            "publication_year": 2020,
            "authorships": [],
            "best_oa_location": None,
            "primary_location": {"landing_page_url": "https://example.com/w456"},
            "abstract_inverted_index": None,
        },
    ]
}

S2_JSON = {
    "data": [
        {
            "paperId": "abc",
            "title": "Selective weeding with deep learning",
            "abstract": "Weeds are detected. Then removed.",
            "year": 2022,
            "authors": [{"name": "Lee"}],
            "externalIds": {"DOI": "10.1000/abc"},
            "openAccessPdf": {"url": "https://files.example.com/abc.pdf"},
            "url": "https://www.semanticscholar.org/paper/abc",
            "publicationDate": "2022-05-01",
            "venue": "Robotics",
        }
    ]
}
