"""출처 어댑터 레지스트리.

새 출처를 추가하려면: ``Source`` 를 상속한 클래스를 만들고 ``REGISTRY`` 에 등록한다.
"""

from __future__ import annotations

import httpx

from ..config import Settings
from .arxiv import ArxivSource
from .base import Source, SourceError, SourceUnavailable
from .openalex import OpenAlexSource
from .semantic_scholar import SemanticScholarSource
from .stubs import CoreSource, DataGoSource, KciSource
from .web_ddg import WebSource

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (ArxivSource, OpenAlexSource, SemanticScholarSource, WebSource, CoreSource, DataGoSource, KciSource)
}

ALIASES = {
    "s2": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "semantic-scholar": "semantic_scholar",
    "ddg": "web",
    "duckduckgo": "web",
    "google": "web",
}


def resolve_names(names) -> list[str]:
    """별칭을 정식 이름으로 바꾸고 순서를 유지한 채 중복을 없앤다."""
    out: list[str] = []
    for n in names or []:
        key = (n or "").strip().lower()
        key = ALIASES.get(key, key)
        if key and key not in out:
            out.append(key)
    return out


def make_sources(
    names, settings: Settings, client: httpx.AsyncClient | None
) -> tuple[list[Source], list[str]]:
    """이름 목록 → (사용 가능한 어댑터 인스턴스들, 경고 메시지들)."""
    sources: list[Source] = []
    warnings: list[str] = []
    for name in resolve_names(names):
        cls = REGISTRY.get(name)
        if cls is None:
            warnings.append(f"알 수 없는 출처: {name} (사용 가능: {', '.join(REGISTRY)})")
            continue
        src = cls(settings, client)
        ok, reason = src.available()
        if not ok:
            warnings.append(f"{src.label}: 사용 불가 — {reason}")
            continue
        sources.append(src)
    return sources, warnings


def describe_sources(settings: Settings) -> list[dict]:
    """`finder sources` 와 웹 UI 가 쓰는 출처 목록."""
    out = []
    for name, cls in REGISTRY.items():
        src = cls(settings, None)
        ok, reason = src.available()
        out.append(
            {
                "name": name,
                "label": src.label,
                "kind": src.kind,
                "requires_key": src.requires_key,
                "key_env": src.key_env,
                "available": ok,
                "reason": reason,
            }
        )
    return out


__all__ = [
    "REGISTRY",
    "ALIASES",
    "Source",
    "SourceError",
    "SourceUnavailable",
    "resolve_names",
    "make_sources",
    "describe_sources",
]
