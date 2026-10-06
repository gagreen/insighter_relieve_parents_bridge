"""아맘때 '상담 브릿지' 데모 (specs/poc.md 5장).

실행: streamlit run app/main.py
A 쉬운 말 결과 / B 질문 도우미 / C 상담 브리프. 기준 샘플 1건(spec 2-3)으로 동작한다.
노트·브리프는 이 화면을 연 뒤의 기록만 넣는다(spec 5장 세션 범위). 로그인·노트 수정·승인은 없다.
"""
import json
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import baseline_svg  # noqa: E402

from bridge import brief, config, db, notes, pipeline  # noqa: E402
from bridge.evidence import item_label  # noqa: E402

BASE_RESULT_ID = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))["result_id"]


@st.cache_resource
def _init_db(path: str) -> str:
    """첫 실행 시 스키마 생성 + 샘플 적재 (다시 실행해도 중복 없음, CLAUDE.md 8-3)."""
    db.init(path)
    return path


def _conn():
    return db.connect(_init_db(str(config.DB_PATH)))


def _result_id() -> str:
    """BRIDGE_RESULT_ID(셸 또는 .env)로 결과를 고른다. 없으면 기준 샘플 (spec 2-4-1)."""
    return os.environ.get("BRIDGE_RESULT_ID") or BASE_RESULT_ID


def _start_session() -> None:
    conn = _conn()
    st.session_state.ctx = pipeline.load_context(conn, _result_id())
    st.session_state.since = conn.execute("SELECT COALESCE(MAX(turn_id), 0) FROM qa_turns").fetchone()[0]
    st.session_state.messages = []
    st.session_state.stopped = False
    st.session_state.brief = None
    st.session_state.saved_phrases = set()
    conn.close()


def _on_question() -> None:
    """질문 처리는 화면을 그리기 전에 한다(위기 시 같은 실행에서 입력 창을 막기 위해)."""
    question = st.session_state.get("question")
    if not question:
        return
    conn = _conn()
    try:
        result = pipeline.handle_question(conn, st.session_state.ctx, question,
                                          since_turn_id=st.session_state.since)   # 상담 준비 안내의 노트 범위 (PoC2-15)
    finally:
        conn.close()
    st.session_state.messages.append({"role": "user", "text": question, "masked": result.question_masked})
    st.session_state.messages.append({"role": "assistant", "text": result.message, "label": result.label,
                                      "evidence_ids": result.evidence_ids})
    if result.stopped:
        st.session_state.stopped = True


def _chips(ctx: pipeline.Context, ids: list[str]) -> str:
    return " | ".join(item_label(ctx.pack.items[i]) if i in ctx.pack.items else i for i in ids)


def _save_phrase(finding_id: str, term_id: str) -> None:
    """PoC1-11: 해석 표현을 상담 질문으로 저장 (LLM 없음)."""
    ctx = st.session_state.ctx
    term = next(g for g in ctx.glossary if g["id"] == term_id)
    conn = _conn()
    try:
        notes.save_report_phrase(conn, ctx.child_id, finding_id, term, ctx.phrases)
    finally:
        conn.close()
    st.session_state.saved_phrases.add((finding_id, term_id))


def _score_block(item: dict, ctx: pipeline.Context) -> None:
    with st.container(border=True):
        st.subheader(item["name"])
        if item["status"] == "not_administered":
            st.markdown("**미실시**")
            st.caption(item["status_text"])
        else:
            range_text = item["range_label"] or "구간 판정 기준 없음"
            st.markdown(f"T점수 **{item['t']}** · {range_text}")
            for text in (item["percentile_text"], item["direction_note"]):
                if text:
                    st.caption(text)
        st.markdown(baseline_svg(item, ctx.definition["range_labels"]), unsafe_allow_html=True)
        explanation = item["explanation"]
        with st.expander("설명 보기"):
            if explanation["kind"] == "card":
                card = explanation["card"]
                st.caption(explanation["label"])
                st.markdown(card["what_it_asks"])
                st.markdown("\n".join(f"- {e}" for e in card["behavior_examples"]))
                st.markdown(card["position_text"])
                st.markdown(card["report_recommendation"])
            elif explanation["section_titles"]:
                st.caption(f"설명 카드가 없는 항목입니다. 보고서 원문은 {', '.join(explanation['section_titles'])}에 있습니다.")
            else:
                st.caption("설명 카드가 없는 항목입니다.")


def _finding_block(block: dict, ctx: pipeline.Context) -> None:
    """PoC1-09·10: 보고서 원문 그대로 + 풀이가 붙은 낱말 굵게 + 낱말 풀이 목록."""
    if heading := block["heading"]:
        parts = [f"**{heading['name']}**"]
        if heading["t"] is not None:
            parts.append(f"T {heading['t']}")
        if heading["range_label"]:
            parts.append(heading["range_label"])
        st.markdown(" · ".join(parts))
    text = "".join(f"**{s['text']}**" if s["term_id"] else s["text"] for s in block["segments"])
    st.markdown(text.replace("\n", "  \n"))
    terms = {g["id"]: g for g in ctx.glossary}
    linked = [(s["text"], terms[s["term_id"]]) for s in block["segments"] if s["term_id"]]
    if not linked:
        return
    with st.expander(f"낱말 풀이 ({len(linked)}) · 초안(검수 전)"):
        for word, term in linked:
            st.markdown(f"**{word}** — {term['plain']}")
            if term["kind"] == "interpretive":
                st.caption(ctx.phrases["interpretive_note"])
                if (block["id"], term["id"]) in st.session_state.saved_phrases:
                    st.caption(ctx.phrases["report_phrase_saved"])
                else:
                    st.button("상담 질문으로 저장", key=f"save:{block['id']}:{term['id']}",
                              on_click=_save_phrase, args=(block["id"], term["id"]))


def results_tab(ctx: pipeline.Context) -> None:
    view = ctx.view
    st.info(view["notice"])
    st.markdown(f"**한 줄 요약** — {view['summary']['text']}")
    st.caption("초안(검수 전) · 미리 만든 문장을 조립했습니다.")
    items = {i["id"]: i for i in view["items"]}
    for section in view["sections"]:
        if section["title"]:
            st.markdown(f"### {section['title']}")
        for block in section["blocks"]:
            if block["kind"] == "subgroup":
                st.markdown(f"**{block['title']}**")
            elif block["kind"] == "score":
                _score_block(items[block["id"]], ctx)
            else:
                _finding_block(block, ctx)


def qa_tab(ctx: pipeline.Context) -> None:
    st.info(ctx.phrases["fixed_notice_qa"])
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m["role"] == "user" and m.get("masked"):
                st.caption(f"AI에게 보낸 문장: {m['masked']}")
            if m["role"] == "assistant":
                caption = m["label"] or ""
                if m["evidence_ids"]:
                    prefix = "근거" if m["label"] == pipeline.LABEL_AI else "관련 항목"
                    caption += f" · {prefix}: {_chips(ctx, m['evidence_ids'])}"
                st.caption(caption)
    if st.session_state.stopped:
        st.warning("안전을 위해 질문 도우미 대화를 멈췄습니다.")
    st.chat_input("보고서에 대해 궁금한 점을 물어보세요", key="question", on_submit=_on_question,
                  disabled=st.session_state.stopped)

    conn = _conn()
    items = notes.list_notes(conn, ctx.child_id, st.session_state.since)
    conn.close()
    st.markdown(f"**질문 노트 ({len(items)})**")
    for n in items:
        st.markdown(f"- {n['text']}")


def brief_tab(ctx: pipeline.Context) -> None:
    st.caption("상담사가 상담 전에 읽는 텍스트입니다. 질문 정리는 AI가 하고(검수 전), 나머지는 코드가 조립합니다.")
    if st.button("브리프 만들기", key="make_brief"):
        conn = _conn()
        try:
            since = st.session_state.since
            organized = notes.organize_notes(conn, notes.list_notes(conn, ctx.child_id, since))
            st.session_state.brief = brief.build_brief(ctx, organized, brief.answered_turns(conn, ctx.child_id, since),
                                                       brief.crisis_turns(conn, ctx.child_id, since))
        finally:
            conn.close()
    if st.session_state.brief:
        st.code(st.session_state.brief, language=None)


st.set_page_config(page_title="상담 브릿지 데모", layout="centered")
st.title("아맘때 '상담 브릿지' 데모")
if "ctx" not in st.session_state:
    try:
        _start_session()
    except KeyError:
        st.error(f"검사 결과를 찾을 수 없습니다: {_result_id()} (BRIDGE_RESULT_ID 확인, `python -m bridge.db init`으로 적재)")
        st.stop()
context = st.session_state.ctx
st.caption(f"검사 결과 {context.result_id}")

tab_results, tab_qa, tab_brief = st.tabs(["쉬운 말 결과", "질문 도우미", "상담 브리프"])
with tab_results:
    results_tab(context)
with tab_qa:
    qa_tab(context)
with tab_brief:
    brief_tab(context)
