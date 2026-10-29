"""출처 어댑터 공통 기반: 인터페이스, 속도 제한, 재시도."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

import httpx

from ..config import Settings
from ..models import Result

log = logging.getLogger("topic_finder.sources")

RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(Exception):
    """출처 호출 실패 (네트워크·HTTP·파싱)."""


class SourceUnavailable(SourceError):
    """키 없음 / 미구현 / 패키지 없음 — 설정으로 해결해야 하는 상태."""


class RateLimiter:
    """출처별 최소 요청 간격을 보장한다 (초당 rps 회)."""

    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps if rps and rps > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.min_interval:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class Source(ABC):
    """모든 출처 어댑터의 공통 인터페이스.

    하위 클래스는 ``_search`` 만 구현하면 된다. ``search`` 가 속도 제한을 처리한다.
    """

    name: str = ""
    label: str = ""
    kind: str = "academic"  # academic → 영어 키워드 사용 / web → 한국어 주제 사용
    requires_key: bool = False
    key_env: str | None = None

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client
        self.limiter = RateLimiter(settings.rate_limits.get(self.name, 1.0))

    def available(self) -> tuple[bool, str]:
        """(사용 가능 여부, 불가 사유)."""
        return True, ""

    async def search(
        self, query: str, limit: int, *, year_from: int | None = None, year_to: int | None = None
    ) -> list[Result]:
        await self.limiter.wait()
        results = await self._search(query, limit, year_from=year_from, year_to=year_to)
        log.info("%s: '%s' → %d건", self.name, query, len(results))
        return results

    @abstractmethod
    async def _search(
        self, query: str, limit: int, *, year_from: int | None, year_to: int | None
    ) -> list[Result]: ...

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        """GET + 재시도(429/5xx/네트워크 오류, 지수 백오프)."""
        if self.client is None:
            raise SourceError(f"{self.name}: HTTP 클라이언트가 없습니다")
        retries = self.settings.retries
        for attempt in range(retries + 1):
            try:
                resp = await self.client.get(url, **kwargs)
            except httpx.TransportError as e:
                if attempt >= retries:
                    raise SourceError(f"{self.name}: 네트워크 오류 ({type(e).__name__}: {e})") from e
                await asyncio.sleep(1.5 * (2**attempt))
                continue
            if resp.status_code in RETRY_STATUS and attempt < retries:
                log.warning("%s: HTTP %s — 재시도 %d/%d", self.name, resp.status_code, attempt + 1, retries)
                await asyncio.sleep(1.5 * (2**attempt))
                continue
            if resp.status_code == 429:
                hint = f" — 무료 API 키를 .env 의 {self.key_env} 에 설정하면 한도가 늘어납니다" if self.key_env else ""
                raise SourceError(f"{self.name}: HTTP 429 요청 한도 초과 (잠시 후 다시 시도){hint}")
            if resp.status_code >= 400:
                raise SourceError(f"{self.name}: HTTP {resp.status_code}")
            return resp
        raise SourceError(f"{self.name}: 요청 실패")  # pragma: no cover
