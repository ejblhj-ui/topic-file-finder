import json

import httpx
import respx
import yaml
from typer.testing import CliRunner

from conftest import ARXIV_XML, OPENALEX_JSON
from topic_finder.cli import app

runner = CliRunner()
PDF = b"%PDF-1.4\n%fake\n"


def write_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "download_dir": str(tmp_path / "downloads"),
                "data_dir": str(tmp_path / ".finder"),
                "topics_file": str(tmp_path / "topics.yaml"),
                "seen_db": str(tmp_path / "seen.sqlite"),
                "log_file": str(tmp_path / "logs" / "finder.log"),
                "retries": 0,
                "rate_limits": {"arxiv": 1000, "openalex": 1000, "semantic_scholar": 1000, "web": 1000},
                "timeout": 5,
            }
        ),
        encoding="utf-8",
    )
    return cfg


def invoke(cfg, *args):
    return runner.invoke(app, ["--config", str(cfg), *args], env={"COLUMNS": "200"})


def test_help_and_version(tmp_path):
    assert invoke(write_config(tmp_path), "--help").exit_code == 0
    r = invoke(write_config(tmp_path), "--version")
    assert r.exit_code == 0 and "topic-file-finder" in r.output


def test_sources_command(tmp_path):
    r = invoke(write_config(tmp_path), "sources")
    assert r.exit_code == 0, r.output
    assert "arxiv" in r.output and "openalex" in r.output


@respx.mock
def test_search_then_download_and_export(tmp_path):
    cfg = write_config(tmp_path)
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV_XML))
    respx.get(url__regex=r"https://arxiv\.org/pdf/.*").mock(
        side_effect=lambda request: httpx.Response(
            200, content=PDF + str(request.url).encode(), headers={"content-type": "application/pdf"}
        )
    )
    r = invoke(cfg, "search", "스마트팜 제초 로봇", "--en", "smart farm weeding robot", "--sources", "arxiv", "--no-auto-en")
    assert r.exit_code == 0, r.output
    assert "총 2건" in r.output and "출처: arxiv" in r.output
    saved = json.loads((tmp_path / ".finder" / "results" / "스마트팜-제초-로봇.json").read_text(encoding="utf-8"))
    assert saved["outcome"]["results"][0]["title"] == "Smart Farm Weeding Robot with Vision"

    r2 = invoke(cfg, "download", "--topic", "스마트팜 제초 로봇", "--ids", "1")
    assert r2.exit_code == 0, r2.output
    assert "저장 1" in r2.output
    pdfs = list((tmp_path / "downloads" / "스마트팜-제초-로봇").rglob("*.pdf"))
    assert len(pdfs) == 1 and pdfs[0].read_bytes().startswith(PDF)
    assert list((tmp_path / "downloads").rglob("REPORT.md")) and list((tmp_path / "downloads").rglob("manifest.json"))

    r3 = invoke(cfg, "download", "--topic", "스마트팜 제초 로봇", "--all")
    assert r3.exit_code == 0, r3.output
    assert "중복 건너뜀 1" in r3.output and "저장 1" in r3.output  # 1번은 이미 있음, 2번은 새로 저장

    r4 = invoke(cfg, "export", "--topic", "스마트팜 제초 로봇", "--out", str(tmp_path / "out.csv"))
    assert r4.exit_code == 0 and (tmp_path / "out.csv").exists()

    r5 = invoke(cfg, "download", "--topic", "스마트팜 제초 로봇", "--ids", "9")
    assert r5.exit_code != 0 and "범위" in r5.output


def test_download_without_search_fails(tmp_path):
    r = invoke(write_config(tmp_path), "download", "--topic", "없는 주제", "--all")
    assert r.exit_code != 0 and "먼저 finder search" in r.output


@respx.mock
def test_topics_add_list_run_shows_only_new(tmp_path):
    cfg = write_config(tmp_path)
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX_JSON))
    r = invoke(cfg, "topics", "add", "스마트팜", "--en", "smart farm", "--sources", "openalex")
    assert r.exit_code == 0, r.output
    r = invoke(cfg, "topics", "list")
    assert r.exit_code == 0 and "스마트팜" in r.output and "smart farm" in r.output

    r1 = invoke(cfg, "topics", "run", "스마트팜")
    assert r1.exit_code == 0, r1.output
    assert "총 2건" in r1.output
    r2 = invoke(cfg, "topics", "run", "스마트팜")
    assert r2.exit_code == 0, r2.output
    assert "총 0건" in r2.output and "이미 본 자료 2건 숨김" in r2.output
    r3 = invoke(cfg, "topics", "run", "스마트팜", "--include-seen")
    assert "총 2건" in r3.output
    r4 = invoke(cfg, "topics", "reset", "스마트팜")
    assert r4.exit_code == 0 and "2건 삭제" in r4.output
    assert "총 2건" in invoke(cfg, "topics", "run", "스마트팜").output
    assert invoke(cfg, "topics", "remove", "스마트팜").exit_code == 0
    assert invoke(cfg, "topics", "run", "스마트팜").exit_code != 0
