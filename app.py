"""Streamlit 웹 UI — `streamlit run app.py`. CLI 와 같은 코어 로직(topic_finder)을 사용한다."""

import asyncio
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from topic_finder.config import load_settings, setup_logging
from topic_finder.download import download_results
from topic_finder.models import Topic
from topic_finder.search import search_all
from topic_finder.sources import describe_sources
from topic_finder.summarize import claude_available, claude_keywords_en
from topic_finder.topics import ResultsCache, SeenIndex, TopicStore

st.set_page_config(page_title="주제별 자료 검색·다운로드", page_icon="📚", layout="wide")


@st.cache_resource
def get_settings():
    s = load_settings()
    setup_logging(s)
    return s


settings = get_settings()
store = TopicStore(settings.topics_file)
seen = SeenIndex(settings.seen_db)
source_info = describe_sources(settings)
available = [s["name"] for s in source_info if s["available"]]
labels = {s["name"]: s["label"] for s in source_info}
this_year = datetime.now().year

st.title("📚 주제별 공개 자료 검색·다운로드")
st.caption("논문·보고서·공공자료를 여러 출처에서 한 번에 찾고, 고른 파일을 주제별 폴더에 리포트와 함께 저장합니다.")

# ----------------------------------------------------------------- 사이드바
with st.sidebar:
    st.header("검색 조건")
    saved = store.list()
    names = ["(새 주제)"] + [t.name for t in saved]
    pick = st.selectbox("저장된 주제", names)
    chosen = next((t for t in saved if t.name == pick), None)

    topic = st.text_input("주제 (한국어)", value=chosen.name if chosen else "", placeholder="예: 스마트팜 제초 로봇")
    en = st.text_input(
        "영어 키워드 (해외 학술 출처용, 선택)",
        value=(chosen.en if chosen and chosen.en else ""),
        placeholder="예: smart farm weeding robot",
    )
    default_sources = [
        s for s in (chosen.sources if chosen and chosen.sources else settings.default_sources) if s in available
    ]
    sources = st.multiselect("출처", options=available, default=default_sources, format_func=lambda n: labels.get(n, n))
    limit = st.number_input("최대 결과 수", min_value=5, max_value=200, value=int(chosen.limit if chosen else settings.default_limit), step=5)
    use_years = st.checkbox("연도 범위 적용", value=bool(chosen and (chosen.year_from or chosen.year_to)))
    c1, c2 = st.columns(2)
    year_from = c1.number_input("시작", min_value=1990, max_value=2100, value=int(chosen.year_from) if chosen and chosen.year_from else this_year - 5, disabled=not use_years)
    year_to = c2.number_input("끝", min_value=1990, max_value=2100, value=int(chosen.year_to) if chosen and chosen.year_to else this_year, disabled=not use_years)
    file_type = st.selectbox("웹 검색 파일 유형", ["pdf", "hwp", "docx", "pptx", "xlsx"], index=0)
    only_new = st.checkbox("새 자료만 (이미 본 자료 제외)", value=bool(chosen))
    ko_summary = st.checkbox("한국어 3줄 요약 (Claude API, 키 있을 때만)", value=False, disabled=not claude_available(settings))

    run = st.button("검색", type="primary", use_container_width=True)
    if st.button("현재 조건을 주제로 저장", use_container_width=True):
        if topic.strip():
            store.add(
                Topic(
                    name=topic.strip(), en=en.strip() or None, sources=sources or None, limit=int(limit),
                    year_from=int(year_from) if use_years else None, year_to=int(year_to) if use_years else None,
                    file_types=[file_type],
                )
            )
            st.success(f"'{topic.strip()}' 저장됨 — 다음부터 '저장된 주제'에서 고를 수 있습니다.")
        else:
            st.warning("주제를 먼저 입력하세요.")
    unavailable = [s for s in source_info if not s["available"]]
    if unavailable:
        st.caption("사용 불가 출처: " + ", ".join(f"{s['label']} ({s['reason']})" for s in unavailable))

# ----------------------------------------------------------------- 검색 실행
if run:
    if not topic.strip():
        st.warning("주제를 입력하세요.")
    elif not sources:
        st.warning("출처를 하나 이상 고르세요.")
    else:
        name = topic.strip()
        q_en = en.strip() or None
        if not q_en and claude_available(settings):
            q_en = claude_keywords_en(name, settings)
            if q_en:
                st.info(f"영어 키워드(자동 생성): {q_en}")
        with st.spinner("검색 중…"):
            outcome = asyncio.run(
                search_all(
                    name, q_en, sources=sources, limit=int(limit),
                    year_from=int(year_from) if use_years else None,
                    year_to=int(year_to) if use_years else None,
                    file_types=[file_type], settings=settings, ko_summary=ko_summary,
                )
            )
        hidden = 0
        if only_new:
            before = len(outcome.results)
            outcome.results = seen.filter_new(name, outcome.results)
            hidden = before - len(outcome.results)
        seen.mark(name, outcome.results)
        ResultsCache(settings).save(name, outcome)
        st.session_state.update(outcome=outcome, topic=name, hidden=hidden, report=None)

# ----------------------------------------------------------------- 결과 표시
outcome = st.session_state.get("outcome")
if not outcome:
    st.info("왼쪽에서 주제를 입력하고 **검색**을 누르세요. 결과에서 받을 파일을 체크한 뒤 다운로드하면 "
            "`downloads/<주제>/<날짜>/` 에 파일과 REPORT.md 가 생깁니다.")
else:
    topic_name = st.session_state["topic"]
    st.subheader(f"결과: {topic_name} — {len(outcome.results)}건")
    meta = f"출처: {', '.join(outcome.sources_used) or '없음'}"
    if outcome.query_en:
        meta += f" · 영어 키워드: {outcome.query_en}"
    if st.session_state.get("hidden"):
        meta += f" · 이미 본 자료 {st.session_state['hidden']}건 숨김"
    st.caption(meta)
    for w in outcome.warnings:
        st.warning(w)

    if not outcome.results:
        st.write("결과가 없습니다. 영어 키워드를 바꾸거나 출처를 추가해 보세요.")
    else:
        rows = [
            {
                "선택": False,
                "#": i,
                "제목": r.title,
                "연도": r.year,
                "출처": r.source + (f" +{len(r.extra.get('also_in') or [])}" if r.extra.get("also_in") else ""),
                "PDF": "✓" if r.file_url else "",
                "요약": r.summary or "",
                "링크": r.url or r.file_url or "",
            }
            for i, r in enumerate(outcome.results, 1)
        ]
        df = pd.DataFrame(rows)
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            height=min(60 + 36 * len(rows), 600),
            column_config={
                "선택": st.column_config.CheckboxColumn("선택", default=False, width="small"),
                "#": st.column_config.NumberColumn("#", width="small"),
                "제목": st.column_config.TextColumn("제목", width="large"),
                "연도": st.column_config.NumberColumn("연도", width="small", format="%d"),
                "요약": st.column_config.TextColumn("요약", width="large"),
                "링크": st.column_config.LinkColumn("링크", display_text="열기", width="small"),
            },
            disabled=[c for c in df.columns if c != "선택"],
            key="results_editor",
        )
        selected_idx = [int(i) - 1 for i in edited.loc[edited["선택"] == True, "#"].tolist()]  # noqa: E712

        with st.expander("요약 전체 보기"):
            for i, r in enumerate(outcome.results, 1):
                st.markdown(f"**{i}. {r.title}** ({r.year or '연도 미상'}, {r.source})  \n{r.summary or '(요약 없음)'}")

        b1, b2 = st.columns(2)
        do_sel = b1.button(f"선택 다운로드 ({len(selected_idx)}건)", disabled=not selected_idx, type="primary")
        do_all = b2.button("전체 다운로드 (파일 링크 있는 것)")
        if do_sel or do_all:
            targets = [outcome.results[i] for i in selected_idx] if do_sel else [r for r in outcome.results if r.file_url]
            if not targets:
                st.warning("다운로드할 파일이 없습니다.")
            else:
                bar = st.progress(0.0, text="다운로드 준비…")

                def _cb(done: int, total: int, entry) -> None:
                    bar.progress(done / max(total, 1), text=f"{done}/{total} — {entry.result.title[:50]}")

                report = asyncio.run(download_results(targets, topic_name, settings, progress=_cb))
                bar.progress(1.0, text="완료")
                st.session_state["report"] = report

    report = st.session_state.get("report")
    if report:
        c = report.counts()
        st.success(
            f"저장 {c['ok']} · 중복 건너뜀 {c['skipped_duplicate']} · 링크 없음 {c['no_file_url']} · "
            f"실패 {c['failed'] + c['skipped_too_large']}  →  폴더: `{report.out_dir}`"
        )
        report_path = Path(report.out_dir) / "REPORT.md"
        if report_path.exists():
            with st.expander("REPORT.md 미리보기", expanded=True):
                st.markdown(report_path.read_text(encoding="utf-8"))
