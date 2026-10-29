"""설정 로딩: config.yaml + .env (+ 환경 변수) → Settings."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

DEFAULT_SOURCES = ["arxiv", "openalex", "semantic_scholar", "web"]

# 환경 변수 → Settings 필드
ENV_KEYS = {
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "SEMANTIC_SCHOLAR_API_KEY": "semantic_scholar_api_key",
    "OPENALEX_API_KEY": "openalex_api_key",
    "CORE_API_KEY": "core_api_key",
    "DATAGO_API_KEY": "datago_api_key",
    "KCI_API_KEY": "kci_api_key",
    "FINDER_CONTACT_EMAIL": "contact_email",
    "FINDER_DOWNLOAD_DIR": "download_dir",
}


class Settings(BaseModel):
    contact_email: str = "you@example.com"  # OpenAlex polite pool · User-Agent 연락처
    user_agent: str = "topic-file-finder/0.1 (+mailto:{email})"
    download_dir: Path = Path("downloads")
    data_dir: Path = Path(".finder")  # 마지막 검색 결과 캐시
    topics_file: Path = Path("topics.yaml")
    seen_db: Path = Path("seen.sqlite")
    log_file: Path = Path("logs/finder.log")
    default_sources: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCES))
    default_limit: int = 30
    per_source_limit: int | None = None  # None이면 limit과 동일
    max_file_mb: int = 100
    concurrency: int = 3
    timeout: float = 60.0
    retries: int = 2
    rate_limits: dict[str, float] = Field(  # 출처별 초당 요청 수
        default_factory=lambda: {"arxiv": 0.34, "openalex": 10.0, "semantic_scholar": 1.0, "web": 1.0}
    )
    web_region: str = "auto"  # auto | kr-kr | wt-wt ...
    claude_model: str = "claude-haiku-5-5"
    # API 키 (환경 변수/.env 에서만 읽음)
    anthropic_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    openalex_api_key: str | None = None
    core_api_key: str | None = None
    datago_api_key: str | None = None
    kci_api_key: str | None = None

    @property
    def ua(self) -> str:
        return self.user_agent.format(email=self.contact_email)


def load_settings(config_path: str | Path | None = None, env_file: str | Path | None = ".env") -> Settings:
    """config.yaml 과 .env 를 읽어 Settings 를 만든다. 둘 다 없어도 기본값으로 동작한다."""
    if env_file and Path(env_file).exists():
        load_dotenv(env_file)
    path = Path(config_path or os.environ.get("FINDER_CONFIG", "config.yaml"))
    data: dict = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for env, field in ENV_KEYS.items():
        val = os.environ.get(env)
        if val:
            data[field] = val
    return Settings(**data)


def setup_logging(settings: Settings, verbose: bool = False) -> None:
    """콘솔(rich) + 파일 로깅. 여러 번 불러도 핸들러가 중복되지 않는다."""
    root = logging.getLogger("topic_finder")
    if getattr(root, "_finder_configured", False):
        root.setLevel(logging.DEBUG if verbose else logging.INFO)
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    try:
        from rich.logging import RichHandler

        console = RichHandler(rich_tracebacks=False, show_path=False, markup=False)
    except Exception:  # pragma: no cover
        console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    root.addHandler(console)
    try:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(settings.log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        fh.setLevel(logging.INFO)
        root.addHandler(fh)
    except OSError:  # 로그 파일을 못 만들어도 동작은 계속
        pass
    root._finder_configured = True  # type: ignore[attr-defined]
