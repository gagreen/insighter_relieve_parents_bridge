"""PoC2-12 브리프 텍스트 (M3) [G-10, G-11]. LLM은 모킹한다."""
import pytest

from bridge import brief, db, notes, pipeline
from llm_fakes import FakeClient, fake_response

GOOD = {
    "answerable": True,
    "answer": "주의집중 문제 T점수는 66으로 상위 약 5%이며, 관찰 권고 범위에 있습니다.",
    "evidence_ids": ["III.attention"],
    "note_question": None,
}


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    path = tmp_path_factory.mktemp("brief") / "bridge.db"
    db.init(path)
    conn = db.connect(path)
    ctx = pipeline.load_context(conn, "R-KCBCL_4_17-035")
    since = conn.execute("SELECT COALESCE(MAX(turn_id), 0) FROM qa_turns").fetchone()[0]
    pipeline.handle_question(conn, ctx, "ADHD인가요?", client=FakeClient())                       # 노트(diagnosis)
    pipeline.handle_question(conn, ctx, "아이를 어떻게 훈육해야 하나요?", client=FakeClient())     # 노트(parenting)
    pipeline.handle_question(conn, ctx, "T점수가 무슨 뜻이에요?", client=FakeClient(fake_response(GOOD)))  # AI 답변
    pipeline.handle_question(conn, ctx, "아이가 죽고 싶다고 해요", client=FakeClient())           # 위기
    yield conn, ctx, since
    conn.close()


def _brief(setup, organized=None):
    conn, ctx, since = setup
    items = notes.list_notes(conn, ctx.child_id, since)
    organized = organized or notes.skipped(items)
    return brief.build_brief(ctx, organized, brief.answered_turns(conn, ctx.child_id, since),
                             brief.crisis_turns(conn, ctx.child_id, since))


def test_poc2_12_three_sections(setup):
    text = _brief(setup)
    for heading in ("① 보호자 질문", "② AI가 답한 설명형 질문", "③ 위기 표시"):
        assert heading in text


def test_poc2_12_questions_grouped_by_type_with_ref_names(setup):
    text = _brief(setup)
    assert "[진단·치료·경과]" in text and "[양육]" in text
    assert "ADHD인가요?" in text
    assert "III.attention · 주의집중 문제" in text      # 관련 항목은 id · 이름


def test_poc2_12_ai_answer_listed(setup):
    text = _brief(setup)
    assert "T점수가 무슨 뜻이에요?" in text and GOOD["answer"] in text


def test_g10_crisis_flag_always_included(setup):
    text = _brief(setup)
    section = text.split("③ 위기 표시")[1]
    assert "아이가 죽고 싶다고 해요" in section


def test_poc2_12_does_not_relist_report(setup):
    """보고서 점수 목록·보호자 의견 원문을 다시 나열하지 않는다."""
    conn, ctx, _ = setup
    text = _brief(setup)
    opinions = [f["text"] for f in ctx.payload["findings"] if f["id"].startswith("VII.")]
    assert opinions and not [o for o in opinions if o in text]
    other_scores = [i for i in ctx.view["items"] if i["scale"] not in ("attention",) and i["t"] is not None]
    assert not [i["name"] for i in other_scores if f"{i['name']} T" in text]


def test_poc2_12_skipped_and_fallback_labels(setup):
    conn, ctx, since = setup
    items = notes.list_notes(conn, ctx.child_id, since)
    assert "정리하지 않음" in _brief(setup, notes.skipped(items))
    fallback = notes.OrganizeResult(notes.fallback_items(items), "fallback", [["format:json"]], [])
    assert "자동 정리 실패" in _brief(setup, fallback)


def test_poc2_12_cli_no_llm(setup, capsys):
    conn, ctx, _ = setup
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    assert brief.main(["R-KCBCL_4_17-035", "--db", path, "--no-llm"]) == 0
    assert "① 보호자 질문" in capsys.readouterr().out
