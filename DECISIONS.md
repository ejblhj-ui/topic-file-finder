# DECISIONS — 명세에 없던 부분을 이렇게 정했다

- **arXiv 질의**: 단어를 `AND` 로 묶어 먼저 검색하고, 결과가 8건 미만이면 `OR` 질의(relevance 정렬)로 보충한다. AND 만 쓰면 4단어 주제에서 결과가 4건에 그쳤고, OR 만 쓰면 잡음이 많았다.
- **출처별 질의 언어**: academic(arXiv·OpenAlex·Semantic Scholar)에는 `--en` 영어 키워드(없으면 한국어 주제 그대로), web(DuckDuckGo)에는 한국어 주제를 보낸다. 한글이 포함되면 region `kr-kr`, 아니면 `wt-wt`.
- **최대 결과 수**: `limit` 은 최종 결과 수. 출처마다 `limit` 건씩 받아(중복 제거 재료) 순위 후 `limit` 건으로 자른다. `per_source_limit` 설정으로 바꿀 수 있다.
- **순위 점수**: 제목 키워드 일치 +3/단어, 초록 일치 +1/단어, 최근 10년 선형 가산(최대 +2), 파일 링크 +1.5. 단순 규칙 — 튜닝은 `search.score`.
- **중복 판단**: DOI 정규화 일치 → 동일. 없으면 정규화 제목이 같거나(16자 초과일 때) 유사도 ≥ 0.9. 길이 차 15% 초과면 비교 생략(속도).
- **웹 출처 결과는 전부 file_url 로 본다**: `filetype:pdf` 검색이므로. 실제로 HTML 이 오면 다운로더가 "HTML 페이지" 로 실패 처리한다.
- **다운로드 번호 선택**: `search` 가 결과를 `.finder/results/<주제-슬러그>.json` 에 저장하고 `download --topic` 이 그 번호를 쓴다. 주제 문자열이 같아야 한다.
- **같은 파일 판단은 sha256**: 주제 폴더의 과거 `manifest.json` 들에서 해시를 모아 비교. 같은 날 폴더 안 이름 충돌은 `_2`, `_3` 접미사.
- **seen 기록 시점**: `topics run` 과 웹 UI 검색에서 *표시된* 결과를 바로 본 것으로 기록한다(다운로드 여부 무관). 되돌리려면 `finder topics reset "주제"`.
- **Claude API 는 선택**: `ANTHROPIC_API_KEY` + `anthropic` 패키지가 있을 때만 영어 키워드 자동 생성(기본 켜짐, `--no-auto-en`)과 `--ko-summary`(기본 꺼짐, 상위 10건). 실패하면 조용히 규칙 기반으로 돌아간다. 모델 기본값 `claude-haiku-5-5`.
- **OpenAlex 는 2026년부터 키 없는 요청을 네트워크 IP 당 일일 예산으로 제한**한다. `OPENALEX_API_KEY`(무료) 지원을 추가했고, 429 메시지에 키 안내를 넣었다. Semantic Scholar 도 같은 방식(`SEMANTIC_SCHOLAR_API_KEY`).
- **arXiv PDF 가 404 인 논문이 있다**(철회·소스만 있는 경우). 실패로 기록하고 넘어간다.
- **패키지**: `duckduckgo_search` 는 `ddgs` 로 이름이 바뀌어 `ddgs` 를 쓰고, 구 패키지도 import 가능하면 받아들인다.
- **라이선스 필드**: setuptools 버전에 따라 `license` 표기 규칙이 달라 pyproject 에서 생략하고 `LICENSE` 파일만 둔다.
- **테스트**: 네트워크 없이 돈다. HTTP 는 `respx` 로, DuckDuckGo 는 `_ddg_text` monkeypatch 로 모킹. 속도 제한·재시도는 테스트 설정에서 끈다.
