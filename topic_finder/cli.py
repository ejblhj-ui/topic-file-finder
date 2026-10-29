"""`finder` CLI — search / download / topics / export / sources."""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table

from . import __version__
from .config import Settings, load_settings, setup_logging
from .download import STATUS_KO, DownloadReport, download_results
from .export import export_results
from .models import Result, SearchOutcome, Topic
from .search import search_all
from .sources import describe_sources
from .summarize import claude_available, claude_keywords_en
from .topics import ResultsCache, SeenIndex, TopicStore

app = typer.Typer(
    help="주제별 공개 자료 검색·다운로드 도구. 예: finder search \"스마트팜 제초 로봇\" --en \"smart farm weeding robot\"",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)
topics_app = typer.Typer(help="저장된 주제 관리 (add / list / remove / run / reset)", no_args_is_help=True)
app.add_typer(topics_app, name="topics")
console = Console()


# ----------------------------------------------------------------- 공통


def _split(csv: Optional[str]) -> Optional[list[str]]:
    if not csv:
        return None
    return [s.strip() for s in csv.split(",") if s.strip()]


def _version(value: bool):
    if value:
        console.print(f"topic-file-finder {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="설정 파일 (기본: config.yaml, 없으면 기본값)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="자세한 로그"),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="버전 표시"),
):
    settings = load_settings(config)
    setup_logging(settings, verbose=verbose)
    ctx.obj = settings


def _run_search(settings: Settings, query: str, en: Optional[str], **kw) -> SearchOutcome:
    with console.status("검색 중…"):
        return asyncio.run(search_all(query, en, settings=settings, **kw))


def _print_results(outcome: SearchOutcome, *, title: str) -> None:
    table = Table(title=title, expand=True)
    table.add_column("#", justify="right", width=4)
    table.add_column("제목", ratio=4, overflow="fold")
    table.add_column("연도", width=5, justify="center")
    table.add_column("출처", width=16, overflow="fold")
    table.add_column("PDF", width=4, justify="center")
    table.add_column("요약", ratio=4, overflow="fold")
    for i, r in enumerate(outcome.results, 1):
        also = r.extra.get("also_in") or []
        src = r.source + (f" +{len(also)}" if also else "")
        table.add_row(str(i), r.title, str(r.year or "-"), src, "✓" if r.file_url else "-", (r.summary or "")[:160])
    console.print(table)
    console.print(f"총 {len(outcome.results)}건 · 출처: {', '.join(outcome.sources_used) or '없음'}")
    for w in outcome.warnings:
        console.print(f"[yellow]경고[/] {w}")


def _run_download(settings: Settings, results: list[Result], topic: str) -> DownloadReport:
    with Progress(
        TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn(), console=console
    ) as progress:
        task = progress.add_task("다운로드", total=len(results))

        def cb(done: int, total: int, entry) -> None:
            progress.update(task, completed=done)

        return asyncio.run(download_results(results, topic, settings, progress=cb))


def _print_download_report(report: DownloadReport) -> None:
    c = report.counts()
    console.print(
        f"[bold]다운로드 완료[/] — 저장 {c['ok']} · 중복 건너뜀 {c['skipped_duplicate']} · "
        f"링크 없음 {c['no_file_url']} · 실패 {c['failed'] + c['skipped_too_large']}"
    )
    table = Table(expand=True)
    table.add_column("상태", width=12)
    table.add_column("제목", ratio=3, overflow="fold")
    table.add_column("파일 / 사유", ratio=3, overflow="fold")
    for e in report.entries:
        table.add_row(STATUS_KO.get(e.status, e.status), e.result.title, (Path(e.path).name if e.path else e.reason))
    console.print(table)
    console.print(f"폴더: {report.out_dir}\n리포트: {report.out_dir / 'REPORT.md'}")


def _pick(results: list[Result], ids: str) -> list[Result]:
    chosen: list[Result] = []
    for tok in ids.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:  # 범위 2-5
            a, b = tok.split("-", 1)
            nums = range(int(a), int(b) + 1)
        else:
            nums = [int(tok)]
        for n in nums:
            if n < 1 or n > len(results):
                raise typer.BadParameter(f"번호 {n} 은 범위(1~{len(results)}) 밖입니다")
            if results[n - 1] not in chosen:
                chosen.append(results[n - 1])
    if not chosen:
        raise typer.BadParameter("--ids 에 번호가 없습니다 (예: 1,3,5 또는 2-6)")
    return chosen


# ----------------------------------------------------------------- 명령


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help='한국어 주제 (예: "스마트팜 제초 로봇")'),
    en: Optional[str] = typer.Option(None, "--en", help="영어 키워드 (해외 학술 출처용)"),
    sources: Optional[str] = typer.Option(None, "--sources", "-s", help="쉼표 구분: arxiv,openalex,semantic_scholar,web"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="최대 결과 수 (기본 30)"),
    year_from: Optional[int] = typer.Option(None, "--year-from", help="연도 시작"),
    year_to: Optional[int] = typer.Option(None, "--year-to", help="연도 끝"),
    file_type: str = typer.Option("pdf", "--file-type", help="웹 검색 파일 유형 (pdf, hwp, docx …)"),
    export: Optional[Path] = typer.Option(None, "--export", help="결과 내보내기 (.csv 또는 .md)"),
    save: bool = typer.Option(True, "--save/--no-save", help="결과를 저장해 download 에서 번호로 선택"),
    auto_en: bool = typer.Option(True, "--auto-en/--no-auto-en", help="--en 없을 때 Claude API 로 영어 키워드 생성 (키 있을 때만)"),
    ko_summary: bool = typer.Option(False, "--ko-summary", help="상위 10건을 Claude API 로 한국어 3줄 요약 (키 있을 때만)"),
):
    """주제로 여러 출처를 검색해 표로 보여 준다."""
    settings: Settings = ctx.obj
    if not en and auto_en and claude_available(settings):
        en = claude_keywords_en(query, settings)
        if en:
            console.print(f"[dim]영어 키워드(자동 생성): {en}[/]")
    outcome = _run_search(
        settings, query, en,
        sources=_split(sources), limit=limit or settings.default_limit,
        year_from=year_from, year_to=year_to, file_types=[file_type] if file_type else [],
        ko_summary=ko_summary,
    )
    _print_results(outcome, title=f"검색: {query}" + (f" / {en}" if en else ""))
    if save:
        path = ResultsCache(settings).save(query, outcome)
        console.print(f'[dim]결과 저장: {path}\n→ 다운로드: finder download --topic "{query}" --ids 1,3  (또는 --all)[/]')
    if export:
        export_results(outcome.results, export)
        console.print(f"내보내기: {export}")


@app.command()
def download(
    ctx: typer.Context,
    topic: str = typer.Option(..., "--topic", "-t", help="search 때 쓴 주제 (저장된 결과를 불러옴)"),
    ids: Optional[str] = typer.Option(None, "--ids", help="표의 번호, 쉼표 구분 (예: 1,3,5 또는 2-6)"),
    all_: bool = typer.Option(False, "--all", help="파일 링크가 있는 결과 전부"),
    out_dir: Optional[Path] = typer.Option(None, "--dir", help="저장 루트 폴더 (기본: 설정의 download_dir)"),
):
    """저장된 검색 결과에서 고른 파일을 주제별 폴더에 내려받는다."""
    settings: Settings = ctx.obj
    if out_dir:
        settings = settings.model_copy(update={"download_dir": out_dir})
    cached = ResultsCache(settings).load(topic)
    if cached is None:
        raise typer.BadParameter(f"'{topic}' 의 저장된 검색 결과가 없습니다. 먼저 finder search 를 실행하세요.")
    if all_:
        selected = [r for r in cached.results if r.file_url]
        if not selected:
            console.print("파일 링크가 있는 결과가 없습니다.")
            raise typer.Exit()
    elif ids:
        selected = _pick(cached.results, ids)
    else:
        raise typer.BadParameter("--ids 또는 --all 중 하나를 지정하세요.")
    report = _run_download(settings, selected, topic)
    _print_download_report(report)


@app.command()
def export(
    ctx: typer.Context,
    topic: str = typer.Option(..., "--topic", "-t", help="search 때 쓴 주제"),
    out: Path = typer.Option(..., "--out", "-o", help="저장 경로 (.csv 또는 .md)"),
):
    """저장된 검색 결과를 CSV/Markdown 으로 내보낸다."""
    settings: Settings = ctx.obj
    cached = ResultsCache(settings).load(topic)
    if cached is None:
        raise typer.BadParameter(f"'{topic}' 의 저장된 검색 결과가 없습니다. 먼저 finder search 를 실행하세요.")
    export_results(cached.results, out)
    console.print(f"내보내기: {out} ({len(cached.results)}건)")


@app.command()
def sources(ctx: typer.Context):
    """출처 목록과 사용 가능 여부."""
    settings: Settings = ctx.obj
    table = Table(title="출처", expand=True)
    table.add_column("이름", width=18)
    table.add_column("설명", ratio=2)
    table.add_column("종류", width=10)
    table.add_column("사용 가능", width=9, justify="center")
    table.add_column("비고", ratio=2)
    for s in describe_sources(settings):
        table.add_row(s["name"], s["label"], s["kind"], "✓" if s["available"] else "✗", s["reason"])
    console.print(table)


# ----------------------------------------------------------------- topics


@topics_app.command("add")
def topics_add(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="한국어 주제"),
    en: Optional[str] = typer.Option(None, "--en", help="영어 키워드"),
    sources: Optional[str] = typer.Option(None, "--sources", "-s", help="쉼표 구분 (기본: 설정의 default_sources)"),
    limit: int = typer.Option(30, "--limit", "-n"),
    year_from: Optional[int] = typer.Option(None, "--year-from"),
    year_to: Optional[int] = typer.Option(None, "--year-to"),
    file_type: str = typer.Option("pdf", "--file-type"),
):
    """주제를 저장한다 (같은 이름이면 덮어씀)."""
    settings: Settings = ctx.obj
    topic = Topic(
        name=name.strip(), en=en, sources=_split(sources), limit=limit,
        year_from=year_from, year_to=year_to, file_types=[file_type] if file_type else [],
    )
    TopicStore(settings.topics_file).add(topic)
    console.print(f"저장됨: {topic.name}  →  finder topics run \"{topic.name}\"")


@topics_app.command("list")
def topics_list(ctx: typer.Context):
    """저장된 주제 목록."""
    settings: Settings = ctx.obj
    topics = TopicStore(settings.topics_file).list()
    if not topics:
        console.print("저장된 주제가 없습니다. finder topics add \"주제\" --en \"keywords\"")
        return
    seen = SeenIndex(settings.seen_db)
    table = Table(title="저장된 주제", expand=True)
    table.add_column("주제", ratio=2)
    table.add_column("영어 키워드", ratio=2)
    table.add_column("출처", ratio=2)
    table.add_column("최대", width=5, justify="right")
    table.add_column("연도", width=11)
    table.add_column("본 자료", width=8, justify="right")
    for t in topics:
        years = f"{t.year_from or ''}~{t.year_to or ''}" if (t.year_from or t.year_to) else "-"
        table.add_row(t.name, t.en or "-", ", ".join(t.sources) if t.sources else "(기본)", str(t.limit), years, str(seen.count(t.name)))
    console.print(table)


@topics_app.command("remove")
def topics_remove(ctx: typer.Context, name: str = typer.Argument(...)):
    """저장된 주제를 지운다 (seen 기록은 유지)."""
    settings: Settings = ctx.obj
    if TopicStore(settings.topics_file).remove(name):
        console.print(f"삭제됨: {name}")
    else:
        raise typer.BadParameter(f"'{name}' 주제가 없습니다")


@topics_app.command("reset")
def topics_reset(ctx: typer.Context, name: str = typer.Argument(...)):
    """주제의 '본 자료' 기록을 지워 다음 run 에서 전부 다시 보이게 한다."""
    settings: Settings = ctx.obj
    n = SeenIndex(settings.seen_db).clear(name.strip())
    console.print(f"'{name}' 의 본 자료 기록 {n}건 삭제")


@topics_app.command("run")
def topics_run(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="저장된 주제 이름"),
    include_seen: bool = typer.Option(False, "--include-seen", help="이미 본 자료도 표시"),
    download: bool = typer.Option(False, "--download", help="새 자료 중 파일 링크 있는 것을 모두 다운로드"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="이번 실행만 최대 결과 수 변경"),
):
    """저장된 주제를 다시 검색한다 — 기본으로 새 자료만 보여 준다."""
    settings: Settings = ctx.obj
    topic = TopicStore(settings.topics_file).get(name)
    if topic is None:
        raise typer.BadParameter(f"'{name}' 주제가 없습니다. finder topics list 로 확인하세요.")
    outcome = _run_search(
        settings, topic.name, topic.en,
        sources=topic.sources, limit=limit or topic.limit,
        year_from=topic.year_from, year_to=topic.year_to, file_types=topic.file_types,
    )
    seen = SeenIndex(settings.seen_db)
    hidden = 0
    if not include_seen:
        before = len(outcome.results)
        outcome.results = seen.filter_new(topic.name, outcome.results)
        hidden = before - len(outcome.results)
    _print_results(outcome, title=f"주제: {topic.name} ({'전체' if include_seen else '새 자료만'})")
    if hidden:
        console.print(f"[dim]이미 본 자료 {hidden}건 숨김 (--include-seen 으로 표시)[/]")
    seen.mark(topic.name, outcome.results)
    ResultsCache(settings).save(topic.name, outcome)
    if download:
        targets = [r for r in outcome.results if r.file_url]
        if targets:
            _print_download_report(_run_download(settings, targets, topic.name))
        else:
            console.print("다운로드할 새 파일이 없습니다.")


if __name__ == "__main__":  # pragma: no cover
    app()
