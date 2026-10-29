"""요약: 규칙 기반(초록 앞 문장) + 선택적 Claude API (키가 있을 때만)."""

from __future__ import annotations

import logging
import re

from .config import Settings

log = logging.getLogger("topic_finder.summarize")

# 영문 문장 끝(. ! ?) 또는 한국어 '다.' 뒤에서 자른다
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s*")


def rule_summary(text: str | None, max_sentences: int = 3, max_chars: int = 400) -> str | None:
    """초록 앞 2~3문장을 짧은 요약으로 쓴다. 외부 의존성 없음."""
    if not text:
        return None
    text = " ".join(text.split())
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    out = " ".join(parts[:max_sentences]) if parts else text
    if len(out) > max_chars:
        out = out[: max_chars - 1].rstrip() + "…"
    return out or None


def claude_available(settings: Settings) -> bool:
    if not settings.anthropic_api_key:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _ask(settings: Settings, prompt: str, max_tokens: int = 300) -> str | None:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in msg.content).strip()
        return text or None
    except Exception as e:  # 어떤 이유로든 실패하면 조용히 규칙 기반으로 돌아간다
        log.warning("Claude API 호출 실패: %s", e)
        return None


def claude_keywords_en(topic_ko: str, settings: Settings) -> str | None:
    """한국어 주제 → 학술 검색용 영어 키워드 (3~8단어)."""
    if not claude_available(settings):
        return None
    prompt = (
        "다음 한국어 주제를 영어 학술 검색 키워드로 바꿔 주세요. "
        "3~8개 단어, 한 줄, 따옴표·설명·불릿 없이 키워드만 출력하세요.\n"
        f"주제: {topic_ko}"
    )
    out = _ask(settings, prompt, max_tokens=60)
    if not out:
        return None
    return out.splitlines()[0].strip().strip('"').strip("'") or None


def claude_summary_ko(title: str, abstract: str | None, settings: Settings) -> str | None:
    """논문/자료를 한국어 3줄로 요약."""
    if not claude_available(settings) or not abstract:
        return None
    prompt = (
        "다음 자료를 한국어 3줄로 요약하세요. 각 줄은 한 문장, 불릿·번호 없이 줄바꿈으로만 구분하세요.\n"
        f"제목: {title}\n내용: {abstract[:3000]}"
    )
    return _ask(settings, prompt, max_tokens=300)
