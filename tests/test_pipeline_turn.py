"""질문 1건 처리 handle_question [CLAUDE.md 6장, PoC2-01·02·03·05·06·07·08·10·13, G-05, G-06, G-09, G-11].

LLM은 모킹한다. DB는 이 모듈 전용 임시 파일.
"""
import json
import logging

import anthropic
import httpx2
import pytest

from bridge import config, db, notes, pipeline
from llm_fakes import FakeClient, fake_response

GOOD = {
    "answerable": True,
    "answer": "주의집중 문제 T점수는 66으로 상위 약 5%이며, 관찰 권고 범위에 있습니다. 자세한 의미는 상담에서 다룰 수 있습니다.",
    "evidence_ids": ["III.attention"],
    "note_question": "주의집중 문제 점수의 의미를 알고 싶어요.",
}
BAD_NUMBERS = {**GOOD, "answer": "또래 100명 중 약 92명보다 높다는 뜻입니다.", "evidence_ids": ["term.percentile"]}
EXPLAIN_Q = "T점수가 무슨 뜻이에요?"            # 키워드로 explain
UNDECIDED_Q = "재원이가 요즘 밤에 잠을 잘 못 자요"  # 키워드 없음 + 아동 이름
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("turn") / "bridge.db"
    db.init(path)
    c = db.connect(path)
    yield c
    c.close()


@pytest.fixture(scope="module")
def ctx(conn):
    return pipeline.load_context(conn, "R-KCBCL_4_17-035")


def _turn(conn, turn_id):
    return dict(conn.execute("SELECT * FROM qa_turns WHERE turn_id = ?", (turn_id,)).fetchone())


def _calls(conn, turn_id):
    return [dict(r) for r in conn.execute("SELECT * FROM llm_calls WHERE turn_id = ? ORDER BY call_id", (turn_id,))]


def _notes(conn, turn_id):
    return [dict(r) for r in conn.execute("SELECT * FROM note_items WHERE source_turn_id = ?", (turn_id,))]


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── PoC2-01 입력 검증 ───────────────────────────────


@pytest.mark.parametrize("raw", ["   ", "가" * (config.MAX_INPUT_CHARS + 1)])
def test_poc2_01_invalid_input_is_not_saved(conn, ctx, raw):
    before = _count(conn, "qa_turns")
    r = pipeline.handle_question(conn, ctx, raw, client=FakeClient())
    assert (r.route, r.turn_id) == ("input_error", None) and r.message
    assert _count(conn, "qa_turns") == before


# ── PoC2-02 마스킹 (G-09) ───────────────────────────


def test_g09_masked_question_is_stored_and_sent(conn, ctx):
    client = FakeClient(fake_response({"intent": "explain", "confidence": 0.9}), fake_response(GOOD))
    r = pipeline.handle_question(conn, ctx, UNDECIDED_Q, client=client)
    assert _turn(conn, r.turn_id)["question_masked"] == "[이름]이가 요즘 밤에 잠을 잘 못 자요"
    assert r.question_masked == "[이름]이가 요즘 밤에 잠을 잘 못 자요"   # 화면에 'AI에게 보낸 문장'으로 표시
    sent = json.dumps(client.calls, ensure_ascii=False, default=str)
    assert "재원" not in sent and "백재원" not in sent


# ── PoC2-03 위기 (G-05) ─────────────────────────────


def test_poc2_03_crisis_keyword(conn, ctx, caplog):
    client = FakeClient()
    with caplog.at_level(logging.WARNING, logger="bridge.alert"):
        r = pipeline.handle_question(conn, ctx, "아이가 죽고 싶다고 해요", client=client)
    assert (r.route, r.crisis, r.stopped, r.note_saved) == ("crisis", True, True, False)
    assert client.calls == []
    assert ctx.crisis["message"] in r.message and "109" in r.message
    row = _turn(conn, r.turn_id)
    assert (row["crisis_flag"], row["route"], row["intent"]) == (1, "crisis", "crisis")
    alerts = [rec for rec in caplog.records if rec.name == "bridge.alert"]
    assert len(alerts) == 1 and str(r.turn_id) in alerts[0].getMessage()


def test_poc2_03_crisis_by_intent_llm(conn, ctx, caplog):
    client = FakeClient(fake_response({"intent": "crisis", "confidence": 0.8}))
    with caplog.at_level(logging.WARNING, logger="bridge.alert"):
        r = pipeline.handle_question(conn, ctx, "요즘 아이가 너무 이상해요", client=client)
    assert (r.route, r.crisis, r.stopped) == ("crisis", True, True)
    assert [c["stage"] for c in _calls(conn, r.turn_id)] == ["intent"]
    assert len([rec for rec in caplog.records if rec.name == "bridge.alert"]) == 1


# ── PoC2-05 안전 응답, PoC2-06 범위 밖 ──────────────


def test_poc2_05_diagnosis_keyword_safe_response(conn, ctx):
    client = FakeClient()
    r = pipeline.handle_question(conn, ctx, "재원이 ADHD인가요?", client=client)
    assert (r.route, r.label, r.note_saved) == ("safe", pipeline.LABEL_SAFE, True)
    assert client.calls == [] and "66" in r.message
    [note] = _notes(conn, r.turn_id)
    assert (note["type"], note["text"]) == ("diagnosis", "[이름]이 ADHD인가요?")   # 마스킹된 원래 질문
    assert json.loads(note["related_refs"]) == ["III.attention"]


def test_poc2_05_low_confidence(conn, ctx):
    client = FakeClient(fake_response({"intent": "explain", "confidence": 0.2}))
    r = pipeline.handle_question(conn, ctx, "요즘 밤에 잠을 잘 못 자요", client=client)
    assert (r.route, r.note_saved) == ("safe", True)
    assert _notes(conn, r.turn_id)[0]["type"] == "low_confidence"
    assert _turn(conn, r.turn_id)["intent_confidence"] == pytest.approx(0.2)


def test_poc2_06_out_of_scope(conn, ctx):
    r = pipeline.handle_question(conn, ctx, "상담 예약을 바꾸고 싶어요", client=FakeClient())
    assert (r.route, r.message, r.note_saved) == ("redirect", ctx.phrases["out_of_scope"], False)
    assert _notes(conn, r.turn_id) == []


# ── PoC2-07·08 설명형 응답과 출력 검증 ──────────────


def test_poc2_07_valid_answer(conn, ctx):
    r = pipeline.handle_question(conn, ctx, EXPLAIN_Q, client=FakeClient(fake_response(GOOD)))
    assert (r.route, r.guard_result, r.label, r.message) == ("answer", "pass", pipeline.LABEL_AI, GOOD["answer"])
    assert r.evidence_ids == ["III.attention"] and not r.note_saved
    row = _turn(conn, r.turn_id)
    assert json.loads(row["evidence_refs"]) == ["III.attention"] and row["guard_result"] == "pass"
    [call] = _calls(conn, r.turn_id)
    assert call["stage"] == "answer" and call["prompt_version"] == config.PROMPT_VERSIONS["answer"]


def test_poc2_08_regen_then_pass(conn, ctx):
    r = pipeline.handle_question(conn, ctx, EXPLAIN_Q, client=FakeClient(fake_response(BAD_NUMBERS), fake_response(GOOD)))
    assert (r.route, r.guard_result) == ("answer", "regen")
    assert len(_calls(conn, r.turn_id)) == 2
    assert "number:92" in r.guard_failures[0] and r.guard_failures[1] == []


def test_poc2_08_two_failures_fallback(conn, ctx):
    r = pipeline.handle_question(conn, ctx, EXPLAIN_Q,
                                 client=FakeClient(fake_response(BAD_NUMBERS), fake_response("not json")))
    assert (r.route, r.guard_result, r.label, r.note_saved) == ("answer", "fallback", pipeline.LABEL_SAFE, True)
    assert r.message == pipeline.safe_response("guard_fallback", EXPLAIN_Q, ctx)[0]
    assert _notes(conn, r.turn_id)[0]["type"] == "guard_fallback"
    assert _turn(conn, r.turn_id)["guard_result"] == "fallback"


def test_poc2_07_unanswerable(conn, ctx):
    out = {"answerable": False, "answer": "", "evidence_ids": [], "note_question": None}
    r = pipeline.handle_question(conn, ctx, EXPLAIN_Q, client=FakeClient(fake_response(out)))
    assert (r.route, r.guard_result, r.message, r.note_saved) == ("answer", "pass", ctx.phrases["no_evidence"], True)
    assert _notes(conn, r.turn_id)[0]["type"] == "no_evidence"


# ── PoC2-10 API 오류 ────────────────────────────────


def test_poc2_10_api_error_at_answer(conn, ctx):
    r = pipeline.handle_question(conn, ctx, EXPLAIN_Q, client=FakeClient(anthropic.APIConnectionError(request=_REQ)))
    assert (r.route, r.message, r.note_saved) == ("api_error", ctx.phrases["api_error"], True)
    assert _calls(conn, r.turn_id) == [] and _notes(conn, r.turn_id)[0]["type"] == "api_error"


def test_poc2_10_api_error_at_intent(conn, ctx):
    err = anthropic.InternalServerError("x", response=httpx2.Response(500, request=_REQ), body=None)
    r = pipeline.handle_question(conn, ctx, "요즘 밤에 잠을 잘 못 자요", client=FakeClient(err))
    assert (r.route, r.note_saved) == ("api_error", True)


def test_poc2_10_partial_calls_are_recorded(conn, ctx):
    """의도 분류는 성공하고 응답 생성이 실패하면 성공한 호출만 남긴다."""
    client = FakeClient(fake_response({"intent": "explain", "confidence": 0.9}),
                        anthropic.APIConnectionError(request=_REQ))
    r = pipeline.handle_question(conn, ctx, "요즘 밤에 잠을 잘 못 자요", client=client)
    assert r.route == "api_error"
    assert [c["stage"] for c in _calls(conn, r.turn_id)] == ["intent"]


# ── 노트 조회 ───────────────────────────────────────


def test_list_notes_returns_saved_notes(conn, ctx):
    items = notes.list_notes(conn, ctx.child_id)
    assert items and all(i["child_id"] == ctx.child_id for i in items)
    assert all(isinstance(i["related_refs"], list) for i in items)
