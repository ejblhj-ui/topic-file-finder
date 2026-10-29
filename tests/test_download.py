import json
from pathlib import Path

import httpx
import respx

from conftest import make_result
from topic_finder.download import download_results, ext_from, safe_filename, slugify
from topic_finder.export import export_results

PDF = b"%PDF-1.4\n%fake pdf bytes\n"


def test_slugify():
    assert slugify("스마트팜 제초 로봇") == "스마트팜-제초-로봇"
    assert slugify("  3D프린팅 / 메이커교육: 2026 ") == "3D프린팅-메이커교육-2026"
    assert slugify("///") == "topic"


def test_safe_filename_and_ext():
    r = make_result(title='Smart: farm/weeding "robot" with a very long title that goes on and on forever', year=2023, source="arxiv")
    name = safe_filename(r, "pdf")
    assert name.startswith("2023_") and name.endswith("_arxiv.pdf")
    assert "/" not in name and ":" not in name and '"' not in name
    assert len(name) <= 40 + len("2023__arxiv.pdf") + 2
    r2 = make_result(title="x", file_url="https://a/b/report.HWP")
    assert ext_from(r2, None) == "hwp"
    assert ext_from(r2, "application/pdf; charset=binary") == "pdf"
    assert ext_from(r2, "text/html; charset=utf-8") is None


@respx.mock
async def test_download_creates_files_manifest_report(settings, sample_results):
    respx.get("https://files.example.com/a.pdf").mock(
        return_value=httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
    )
    respx.get("https://files.example.com/report.pdf").mock(
        return_value=httpx.Response(200, content=b"<html>login</html>", headers={"content-type": "text/html"})
    )
    progress = []
    report = await download_results(
        sample_results, "스마트팜 제초 로봇", settings, date="2026-10-29",
        progress=lambda done, total, e: progress.append((done, total, e.status)),
    )
    assert report.out_dir == settings.download_dir / "스마트팜-제초-로봇" / "2026-10-29"
    statuses = {e.result.id: e.status for e in report.entries}
    assert statuses == {"arxiv:1": "ok", "openalex:W2": "no_file_url", "web:3": "failed"}
    assert sorted(p[0] for p in progress) == [1, 2, 3] and all(p[1] == 3 for p in progress)

    ok = report.saved[0]
    path = Path(ok.path)
    assert path.exists() and path.read_bytes() == PDF
    assert path.name == "2023_Smart_Farm_Weeding_Robot_with_Vision_arxiv.pdf"
    assert ok.sha256 and ok.bytes == len(PDF)
    assert not list(report.out_dir.glob("*.part"))

    manifest = json.loads((report.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["topic"] == "스마트팜 제초 로봇" and manifest["counts"]["ok"] == 1
    assert manifest["entries"][2]["reason"].startswith("HTML")

    md = (report.out_dir / "REPORT.md").read_text(encoding="utf-8")
    assert md.startswith("# 자료 수집 리포트 — 스마트팜 제초 로봇")
    assert "저장 1 / 중복 건너뜀 0 / 링크 없음 1 / 실패 1" in md
    assert "| 1 | Smart Farm Weeding Robot with Vision | 2023 | arxiv |" in md
    assert "## 실패·건너뜀" in md and "링크 없음" in md


@respx.mock
async def test_duplicate_sha_is_skipped_across_days(settings):
    first = make_result(id="a", title="Paper A", year=2022, file_url="https://f.example.com/a.pdf")
    respx.get("https://f.example.com/a.pdf").mock(
        return_value=httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
    )
    r1 = await download_results([first], "주제", settings, date="2026-10-28")
    assert r1.entries[0].status == "ok"
    # 다른 URL, 같은 내용 → 건너뜀
    second = make_result(id="b", title="Paper A mirror", year=2022, file_url="https://mirror.example.com/a.pdf")
    respx.get("https://mirror.example.com/a.pdf").mock(
        return_value=httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
    )
    r2 = await download_results([second], "주제", settings, date="2026-10-29")
    assert r2.entries[0].status == "skipped_duplicate"
    assert "2026-10-28" in r2.entries[0].reason
    assert list((settings.download_dir / "주제" / "2026-10-29").glob("*.pdf")) == []


@respx.mock
async def test_too_large_and_http_error(settings):
    settings = settings.model_copy(update={"max_file_mb": 1})
    big = make_result(id="big", title="Big", file_url="https://f.example.com/big.pdf")
    bad = make_result(id="bad", title="Bad", file_url="https://f.example.com/missing.pdf")
    respx.get("https://f.example.com/big.pdf").mock(
        return_value=httpx.Response(200, content=b"x", headers={"content-type": "application/pdf", "content-length": str(5 * 1024 * 1024)})
    )
    respx.get("https://f.example.com/missing.pdf").mock(return_value=httpx.Response(404))
    report = await download_results([big, bad], "주제", settings)
    assert [e.status for e in report.entries] == ["skipped_too_large", "failed"]
    assert report.entries[1].reason == "HTTP 404 (파일 없음)"


@respx.mock
async def test_retry_on_503_then_ok(settings):
    settings = settings.model_copy(update={"retries": 1})
    r = make_result(id="r", title="Retry", file_url="https://f.example.com/r.pdf")
    route = respx.get("https://f.example.com/r.pdf")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"}),
    ]
    report = await download_results([r], "주제", settings)
    assert report.entries[0].status == "ok" and route.call_count == 2


def test_export_csv_and_md(tmp_path, sample_results):
    csv_path = export_results(sample_results, tmp_path / "out" / "results.csv")
    text = csv_path.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("#,제목,저자,연도,출처")
    assert "Smart Farm Weeding Robot with Vision" in text
    md_path = export_results(sample_results, tmp_path / "results.md")
    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("| # | 제목 |") and "| 3 | 스마트팜 제초 로봇 기술 동향 보고서 | 2024 | web |" in md
