# topic-file-finder — 주제별 공개 자료 검색·다운로드 앱

> 이 문서는 **Claude Code 클라우드 세션이 이 앱을 처음부터 끝까지 만들기 위한 요구사항 명세**입니다.
> 사람이 자리에 없어도 끝까지 진행할 수 있도록, 애매한 부분은 7장 "결정 원칙"에 따라 스스로 결정하고 `DECISIONS.md`에 기록합니다.

## 1. 목적

- 주제(예: "스마트팜 제초 로봇", "3D프린팅 메이커교육")를 입력하면 **공개 자료**(논문, 보고서, 공공데이터, 기술문서)를 여러 출처에서 찾아 한 번에 목록화하고, 고른 파일을 **주제별 폴더에 내려받아 요약 리포트와 함께 정리**한다.
- 사용자: 1명(개인). 매주 주제를 바꿔가며 반복 사용한다.
- 주 용도: (1) 농업 로봇·스마트팜 창업 자료조사, (2) 고교 3D프린팅 메이커교육 수업자료 수집.
- 비목표: 로그인·유료 사이트 수집, 대량 크롤링, 저작권 자료 무단 복제. **직접 링크로 공개된 파일만** 받는다.

## 2. 사용자 시나리오 (이 네 가지가 동작하면 완성)

1. **검색** — `finder search "스마트팜 제초 로봇" --en "smart farm weeding robot"`
   → 출처 2곳 이상에서 결과 수집, 중복 제거, 순위를 매겨 표로 출력(번호, 제목, 연도, 출처, PDF 여부, 짧은 요약).
2. **다운로드** — `finder download --topic "스마트팜 제초 로봇" --ids 1,3,5` (또는 `--all`)
   → `downloads/스마트팜-제초-로봇/2026-10-29/`에 파일 저장 + `manifest.json` + `REPORT.md` 생성.
3. **반복** — `finder topics add "스마트팜 제초 로봇" --en "..."`로 저장한 뒤 `finder topics run "스마트팜 제초 로봇"`을 다시 실행하면, 이미 본 자료는 제외하고 **새 자료만** 표시.
4. **웹 UI** — `streamlit run app.py`
   → 주제 입력, 출처 선택, 결과 체크, 다운로드 버튼, 진행 상황 표시. CLI와 같은 코어 로직을 사용.

## 3. 기능 요구사항

### 3.1 검색

- 입력: 한국어 주제(필수), 영어 키워드(선택), 출처 선택, 최대 결과 수(기본 30), 연도 범위(선택), 파일 유형 필터(기본 pdf).
- 한국어 주제는 웹 검색에, 영어 키워드는 해외 학술 출처에 사용한다. 영어 키워드가 없으면 한국어 주제를 그대로 모든 출처에 보낸다(결과가 적어도 실패가 아님).
- **출처 어댑터(MVP, API 키 불필요)**
  - arXiv (API) — 논문, PDF 직링크
  - OpenAlex (API, `mailto` 파라미터로 polite pool 사용) — 학술 전반, OA PDF 링크(`best_oa_location`)
  - Semantic Scholar (Graph API, 키 없이 저속 사용) — 논문, `openAccessPdf`
  - DuckDuckGo 웹 검색 (`ddgs` 패키지, 구 `duckduckgo_search`) — 한국어 보고서·정부 자료 등 일반 웹의 PDF (`filetype:pdf` 활용)
  - 선택(키가 있을 때만 활성): CORE, 공공데이터포털(data.go.kr), KCI — 어댑터 틀과 설정 항목만 만들고 구현은 TODO로 남겨도 된다.
- 모든 어댑터는 공통 인터페이스 `search(query, limit) -> list[Result]`를 구현한다.
  `Result` 필드: `id, title, authors, year, source, url(랜딩 페이지), file_url(직링크, 없을 수 있음), file_type, abstract, doi, published_at, extra`.
- 병렬 호출(asyncio + httpx). 어댑터 하나가 실패해도 나머지 결과는 반환하고 경고만 표시한다.
- **중복 제거**: DOI가 같으면 동일. DOI가 없으면 정규화 제목(소문자, 기호·공백 제거)의 유사도 ≥ 0.9이면 동일로 본다. 합칠 때 `file_url`이 있는 쪽을 우선한다.
- **순위**: 제목·초록 내 키워드 일치 점수 + 최근 연도 가산 + `file_url` 존재 시 가산. 단순 규칙 기반이면 충분하다.
- **요약**: 초록 앞 2~3문장을 짧은 요약으로 사용한다. `ANTHROPIC_API_KEY`가 설정되어 있으면 Claude API로 (a) 한국어 주제 → 영어 키워드 자동 생성, (b) 한국어 3줄 요약을 선택적으로 수행한다. **키가 없어도 모든 기능이 동작해야 한다.**

### 3.2 다운로드

- 선택한 결과의 `file_url`을 받아 `downloads/<주제-슬러그>/<YYYY-MM-DD>/`에 저장한다.
- 파일명: `<연도>_<제목 앞 40자>_<출처>.<확장자>` — OS에서 안전한 문자만 사용한다.
- 동시 다운로드 3개 제한, 타임아웃 60초, 재시도 2회(지수 백오프), 파일 크기 상한(기본 100MB), `Content-Type`으로 확장자 보정.
- `manifest.json`: 모든 항목의 메타데이터 + 성공/실패/사유 + 로컬 경로 + sha256.
- `REPORT.md`: 주제, 실행 일시, 사용 출처, 결과 수, 표(제목 / 연도 / 출처 / 요약 / 파일 경로 / 원문 링크), 실패 목록. **주간 정리 문서에 그대로 붙여 넣을 수 있는 형식**으로 만든다.
- 같은 sha256 파일이 이미 있으면 건너뛴다.

### 3.3 주제 관리와 "새 자료만"

- `topics.yaml`에 주제별 설정을 저장한다: 한국어 주제, 영어 키워드, 출처, 필터.
- `seen.sqlite`: 주제별로 이미 표시·다운로드한 결과의 키(DOI 또는 정규화 제목)를 기록한다.
- `finder topics run`은 기본으로 새 자료만 표시한다(`--include-seen`으로 해제).

### 3.4 내보내기

- 결과 목록을 CSV/Markdown으로 내보낸다 (`--export results.csv`, `--export results.md`).

### 3.5 웹 UI (Streamlit)

- 사이드바: 주제 입력, 영어 키워드, 출처 체크박스, 최대 결과 수, 연도 범위, 저장된 주제 선택.
- 본문: 결과 표(체크박스, 제목 링크, 연도, 출처, 요약 펼치기), "선택 다운로드" / "전체 다운로드" 버튼, 진행 바, 완료 후 저장 폴더 경로와 `REPORT.md` 미리보기.
- UI 언어는 한국어.

## 4. 기술 스택과 구조

- Python 3.11+, `pyproject.toml`(PEP 621), 패키지명 `topic_finder`, CLI 엔트리포인트 `finder`.
- 의존성: `httpx`, `typer`, `rich`, `pydantic`, `pyyaml`, `python-dotenv`, `ddgs`, `streamlit`. 테스트: `pytest`, `pytest-asyncio`, `respx`. 선택: `anthropic`.
- 구조:

```
topic_finder/
  models.py        # Result, Topic 등 pydantic 모델
  config.py        # config.yaml + .env 로드
  sources/         # base.py, arxiv.py, openalex.py, semantic_scholar.py, web_ddg.py
                   # (core.py, datago.py, kci.py: 스텁)
  search.py        # 병렬 검색, 중복 제거, 순위
  download.py      # 다운로드, manifest, report
  topics.py        # 주제 저장, seen 인덱스
  summarize.py     # 규칙 기반 요약 + 선택적 Claude API
  cli.py           # typer 명령
app.py             # Streamlit UI
tests/
config.example.yaml
.env.example
DECISIONS.md
LICENSE            # MIT
```

- 네트워크 예의: User-Agent 명시(연락용 이메일은 설정값), 출처별 초당 요청 제한, robots.txt 존중.
- 로깅: rich 콘솔 + `logs/finder.log`.
- 비밀값은 `.env`에만 두고 저장소에 커밋하지 않는다.

## 5. 완료 기준 (모두 만족해야 끝)

- [x] `pip install -e ".[dev]"` 후 `finder --help` 동작
- [x] `pytest` 전부 통과 — 네트워크 없이 (HTTP는 `respx`로 모킹) — 35개
- [x] 외부 API 키 없이 MVP 전체 동작
- [~] 네트워크가 되는 환경에서 `finder search "smart farm weeding robot" --sources arxiv,openalex --limit 20` 실행 시 결과 10개 이상, 출처 2개 이상, 중복 없음 — arXiv 20건 확인. OpenAlex·Semantic Scholar 는 개발 환경의 공용 IP 한도(429)로 미확인 → 8.6 절 참고
- [~] `finder download`로 PDF 2개 이상 실제 저장 + `manifest.json` + `REPORT.md` 생성 확인 — PDF 1개 저장 + manifest + REPORT 확인(다른 1개는 arXiv 쪽 404). 2개 이상은 로컬에서 확인
- [x] `finder topics add/run`이 "새 자료만" 동작 (모킹 테스트)
- [x] `streamlit run app.py`가 오류 없이 뜨고 검색 → 다운로드 흐름이 됨 (기동·렌더링 확인; 실제 흐름은 로컬에서)
- [x] 이 문서 8장 "사용법"에 설치·실행·설정·출처 추가 방법을 한국어로 정리
- 세션 환경에서 외부 네트워크가 막혀 있으면: 모킹 테스트까지 통과시키고, 실제 연결 검증 절차(위 두 항목)를 8장에 "사용자가 로컬에서 확인할 것"으로 적는다.

## 6. 작업 순서 (단계마다 커밋)

1. 스캐폴드: pyproject, 패키지 뼈대, config/env 로딩, 모델, 로깅
2. 출처 어댑터 4개 + 모킹 테스트
3. 병렬 검색 · 중복 제거 · 순위 + 테스트
4. 다운로더 · manifest · REPORT + 테스트
5. CLI 완성 (`search`, `download`, `topics`, `export`)
6. 주제 저장 · seen 인덱스
7. Streamlit UI
8. 선택적 Claude API 요약/키워드 (키 없을 때 우회 동작 확인)
9. 8장 사용법 문서화, 완료 기준 전부 재검증, PR 생성 (이 채팅 빌드에서는 zip 전달)

## 7. 결정 원칙 (질문 대신 스스로 결정)

- 자리에 아무도 없다고 가정하고 끝까지 진행한다. 애매하면 가장 단순하고 흔한 선택을 하고 `DECISIONS.md`에 한 줄로 기록한다.
- 어떤 출처 API가 막혔거나 바뀌었으면, 그 어댑터는 명확한 오류 메시지와 함께 비활성화하고 나머지로 완료 기준을 맞춘다.
- 기능을 더하기보다 완료 기준을 먼저 채운다. 추가 아이디어는 `TODO.md`에 적는다.
- 라이브러리 버전이 안 맞으면 최신 안정 버전으로 교체하고 이유를 기록한다.

## 8. 사용법

### 8.1 설치 (Python 3.11 이상)

```bash
git clone <이 저장소>  &&  cd topic-file-finder
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # 개발·테스트 포함.  Claude API 요약까지 쓰려면: pip install -e ".[dev,llm]"
finder --help
```

### 8.2 설정 (모두 선택 사항)

- `config.example.yaml` → `config.yaml` 로 복사해 수정 (없으면 기본값). 특히 `contact_email` 을 실제 메일로 바꾸면 OpenAlex 가 더 관대하게 응답한다.
- `.env.example` → `.env` 로 복사해 키 입력. **키가 없어도 전부 동작**한다. 다만 같은 IP 를 여러 사람이 쓰는 네트워크(학교·회사)에서는 OpenAlex·Semantic Scholar 가 `429 요청 한도 초과` 를 낼 수 있는데, 두 곳 모두 무료 키(`OPENALEX_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`)를 넣으면 해결된다.
- `ANTHROPIC_API_KEY` 가 있으면 `--en` 을 생략해도 한국어 주제에서 영어 키워드를 자동 생성하고, `--ko-summary` 로 상위 10건을 한국어 3줄로 요약한다.

### 8.3 CLI

```bash
# 1) 검색 — 표의 번호가 다운로드 선택 번호가 된다
finder search "스마트팜 제초 로봇" --en "smart farm weeding robot"
finder search "3D프린팅 메이커교육" --en "3D printing maker education" --sources arxiv,openalex,web --limit 20 --year-from 2020
finder search "스마트팜 제초 로봇" --en "weeding robot" --export results.csv     # .csv 또는 .md
finder search "농촌진흥청 스마트팜 보고서" --sources web --file-type hwp         # 웹 검색 파일 유형 변경

# 2) 다운로드 — downloads/<주제>/<오늘날짜>/ 에 파일 + manifest.json + REPORT.md
finder download --topic "스마트팜 제초 로봇" --ids 1,3,5       # 번호·범위(2-6) 가능
finder download --topic "스마트팜 제초 로봇" --all             # 파일 링크 있는 것 전부
finder download --topic "스마트팜 제초 로봇" --ids 1 --dir ~/자료     # 저장 위치 변경

# 3) 반복 — 주제를 저장해 두고 다시 돌리면 "새 자료만" 보여 준다
finder topics add "스마트팜 제초 로봇" --en "smart farm weeding robot" --sources arxiv,openalex,web
finder topics run "스마트팜 제초 로봇"                 # 이미 본 자료 제외
finder topics run "스마트팜 제초 로봇" --download      # 새 자료 중 파일 있는 것 모두 받기 (주간 실행용)
finder topics run "스마트팜 제초 로봇" --include-seen  # 전부 다시 보기
finder topics list / remove "주제" / reset "주제"       # reset: 본 자료 기록 삭제

# 기타
finder export --topic "스마트팜 제초 로봇" --out results.md
finder sources                                          # 출처 목록·사용 가능 여부
finder --config 다른설정.yaml search ...                # 설정 파일 지정
```

결과 표의 `출처` 열에 `arxiv +1` 처럼 붙는 숫자는 다른 출처에서도 같은 자료가 나와 합쳐졌다는 뜻이다.
`REPORT.md` 의 "요약" 절은 주간 정리 문서에 그대로 붙여 넣을 수 있게 불릿으로 되어 있다.

### 8.4 웹 UI

```bash
streamlit run app.py
```

왼쪽에서 주제·영어 키워드·출처·결과 수·연도를 고르고 **검색** → 표에서 받을 파일을 체크 → **선택 다운로드** 또는 **전체 다운로드**. 완료되면 저장 폴더와 `REPORT.md` 미리보기가 뜬다. "현재 조건을 주제로 저장" 을 누르면 다음부터 "저장된 주제" 에서 고를 수 있고, "새 자료만" 을 켜 두면 이미 본 자료는 빠진다. CLI 와 같은 `topics.yaml` / `seen.sqlite` / `downloads/` 를 쓴다.

### 8.5 출처 어댑터 추가

1. `topic_finder/sources/` 에 파일을 만들고 `Source` 를 상속한다. `name`, `label`, `kind`("academic" 이면 영어 키워드, "web" 이면 한국어 주제를 받음)를 정하고 `_search(query, limit, *, year_from, year_to) -> list[Result]` 만 구현한다. HTTP 는 `self._get(url, params=...)` 를 쓰면 재시도·속도 제한이 따라온다.
2. 키가 필요하면 `requires_key = True`, `key_env = "XXX_API_KEY"` 를 적고 `config.py` 의 `Settings`·`ENV_KEYS` 에 필드를 추가한다. `available()` 에서 키 유무를 돌려준다.
3. `topic_finder/sources/__init__.py` 의 `REGISTRY` 에 클래스를 넣는다. 끝 — CLI·웹 UI·`finder sources` 에 자동으로 나타난다.
4. `tests/test_sources.py` 에 `respx` 로 응답을 모킹한 테스트를 하나 추가한다. `stubs.py` 의 CORE/공공데이터/KCI 틀을 채우면 된다.

### 8.6 검증 — 개발 환경에서 확인한 것과, 사용자가 로컬에서 확인할 것

개발 환경(클라우드)에서 확인함:
- `pip install -e ".[dev]"` → `finder --help`, `finder sources` 동작
- `pytest` 35개 전부 통과 (네트워크 없이)
- arXiv 실제 검색 20건, 실제 PDF 다운로드 → `manifest.json` · `REPORT.md` 생성, 같은 파일 재다운로드 시 "중복 건너뜀"
- `streamlit run app.py` 기동(health OK) 및 화면 렌더링
- `topics add/run` 두 번째 실행에서 "새 자료만" 동작 (모킹 테스트)

**사용자가 로컬에서 확인할 것** (개발 환경은 공용 IP 라 두 출처가 일일 한도로 429 를 냈고, 검색 엔진은 데이터센터 요청을 거부했다):
1. `finder search "smart farm weeding robot" --sources arxiv,openalex,semantic_scholar --limit 20` → 결과 10건 이상, `출처:` 에 2개 이상, 같은 논문이 두 번 나오지 않는지. 429 가 나면 `.env` 에 무료 키를 넣고 다시.
2. `finder search "스마트팜 제초 로봇" --sources web` → 한국어 PDF 가 나오는지 (DuckDuckGo 가 집 네트워크에서는 정상 응답하는 것이 보통).
3. `finder download --topic "smart farm weeding robot" --all` → PDF 2개 이상 저장.
