"""키가 필요한 출처의 스텁 — 설정 항목과 어댑터 틀만 있고 구현은 TODO (TODO.md 참고)."""

from __future__ import annotations

from .base import Source, SourceUnavailable


class _KeyedStub(Source):
    requires_key = True
    key_attr = ""  # Settings 필드명

    def available(self):
        if not getattr(self.settings, self.key_attr, None):
            return False, f"{self.key_env} 없음"
        return False, "미구현 (TODO.md)"

    async def _search(self, query, limit, *, year_from=None, year_to=None):
        ok, reason = self.available()
        raise SourceUnavailable(f"{self.name}: {reason}")


class CoreSource(_KeyedStub):
    name = "core"
    label = "CORE (오픈액세스 통합)"
    key_env = "CORE_API_KEY"
    key_attr = "core_api_key"


class DataGoSource(_KeyedStub):
    name = "datago"
    label = "공공데이터포털 (data.go.kr)"
    kind = "web"
    key_env = "DATAGO_API_KEY"
    key_attr = "datago_api_key"


class KciSource(_KeyedStub):
    name = "kci"
    label = "KCI (한국학술지인용색인)"
    kind = "web"
    key_env = "KCI_API_KEY"
    key_attr = "kci_api_key"
