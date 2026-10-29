"""주제 저장(topics.yaml), seen 인덱스(seen.sqlite), 마지막 검색 결과 캐시(.finder/results)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import yaml

from .config import Settings
from .download import slugify
from .models import Result, SearchOutcome, Topic


class TopicStore:
    """topics.yaml — 주제별 검색 설정."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[Topic]:
        if not self.path.exists():
            return []
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return [Topic(**t) for t in data.get("topics", []) or []]

    def save(self, topics: list[Topic]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"topics": [t.model_dump(exclude_none=True) for t in topics]}
        self.path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def list(self) -> list[Topic]:
        return self.load()

    def get(self, name: str) -> Topic | None:
        name = name.strip()
        return next((t for t in self.load() if t.name == name), None)

    def add(self, topic: Topic) -> Topic:
        """같은 이름이 있으면 덮어쓴다."""
        topics = [t for t in self.load() if t.name != topic.name]
        topics.append(topic)
        self.save(topics)
        return topic

    def remove(self, name: str) -> bool:
        topics = self.load()
        kept = [t for t in topics if t.name != name.strip()]
        if len(kept) == len(topics):
            return False
        self.save(kept)
        return True


class SeenIndex:
    """seen.sqlite — 주제별로 이미 표시·다운로드한 결과 키(DOI 또는 정규화 제목)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS seen ("
                " topic TEXT NOT NULL, key TEXT NOT NULL, title TEXT, source TEXT, first_seen TEXT,"
                " PRIMARY KEY (topic, key))"
            )
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def seen_keys(self, topic: str) -> set[str]:
        with closing(self._conn()) as conn:
            rows = conn.execute("SELECT key FROM seen WHERE topic = ?", (topic,)).fetchall()
        return {r[0] for r in rows}

    def filter_new(self, topic: str, results: list[Result]) -> list[Result]:
        keys = self.seen_keys(topic)
        return [r for r in results if r.key not in keys]

    def mark(self, topic: str, results: list[Result]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = [(topic, r.key, r.title, r.source, now) for r in results]
        with closing(self._conn()) as conn:
            conn.executemany("INSERT OR IGNORE INTO seen VALUES (?, ?, ?, ?, ?)", rows)
            conn.commit()
        return len(rows)

    def count(self, topic: str) -> int:
        with closing(self._conn()) as conn:
            return conn.execute("SELECT COUNT(*) FROM seen WHERE topic = ?", (topic,)).fetchone()[0]

    def clear(self, topic: str) -> int:
        with closing(self._conn()) as conn:
            cur = conn.execute("DELETE FROM seen WHERE topic = ?", (topic,))
            conn.commit()
            return cur.rowcount


class ResultsCache:
    """마지막 검색 결과 — `finder download --topic ... --ids 1,3` 이 번호로 고를 수 있게 저장."""

    def __init__(self, settings: Settings):
        self.dir = Path(settings.data_dir) / "results"

    def path_for(self, topic: str) -> Path:
        return self.dir / f"{slugify(topic)}.json"

    def save(self, topic: str, outcome: SearchOutcome) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(topic)
        payload = {
            "topic": topic,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "outcome": outcome.model_dump(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, topic: str) -> SearchOutcome | None:
        path = self.path_for(topic)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return SearchOutcome.model_validate(data["outcome"])
