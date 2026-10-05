"""PoC1-10 낱말 풀이 [G-01, G-03, G-04, G-11] → B-3, PoC1-11 상담 질문으로 저장 [G-09, G-10]."""
import json

import pytest

from bridge import brief, config, content, db, notes, pipeline, results
from bridge.content import ContentError
from bridge.rules.glossary_match import annotate, term_ids
from conftest import REAL_PRIVATE_RESULTS_DIR
from test_content import _edit, content_copy  # noqa: F401  (픽스처 재사용)

GLOSSARY = content.load_glossary()
BY_ID = {g["id"]: g for g in GLOSSARY}
DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
SAMPLES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.RESULTS_DIR.glob("*.json"))]
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
PRIVATE = sorted(REAL_PRIVATE_RESULTS_DIR.glob("*.json")) if REAL_PRIVATE_RESULTS_DIR.exists() else []

# 대상 표현 (spec PoC1-10): (원문 표현, 연결될 용어 id)
BASE_TARGETS = [
    ("T=64", "term.notation_t"), ("63T", "term.notation_t"), ("90%tile", "term.notation_percentile"),
    ("상승", "term.elevated"), ("양상", "term.pattern"), ("내재화 문제", "term.internalizing"),
    ("외현화 문제", "term.externalizing"), ("임상 기준", "term.clinical_cutoff"), ("규준", "term.norm"),
    ("교사용 TRF", "term.trf"), ("자기보고형", "term.ysr"), ("다면적 정보", "term.multi_informant"),
    ("준임상 범위", "term.range_borderline"), ("시사", "term.suggests"),
    ("발달적 전이", "term.developmental_transition"),
]
PRIVATE_TARGETS = [
    ("T=61", "term.notation_t"), ("60T", "term.notation_t"), ("85%tile", "term.notation_percentile"),
    ("의존적 양상", "term.dependent"), ("선별 기준", "term.screening_cutoff"), ("준임상 범위", "term.range_borderline"),
    ("교사용 TRF", "term.trf"), ("자기보고형", "term.ysr"), ("규준", "term.norm"),
    ("악화 가능성", "term.worsening"), ("취약 요인", "term.vulnerability_factor"),
    ("기능 저하", "term.function_decline"), ("발달적 전이", "term.developmental_transition"),
    ("정서적 취약성", "term.emotional_vulnerability"), ("시사", "term.suggests"),
    ("학령기 적응", "term.school_adjustment"),
]
INTERPRETIVE = ["term.worsening", "term.vulnerability_factor", "term.function_decline",
                "term.developmental_transition", "term.emotional_vulnerability", "term.suggests"]


def _linked(payloads):
    out = set()
    for payload in payloads:
        for f in payload["findings"]:
            out |= {(s["text"], s["term_id"]) for s in annotate(f["text"], GLOSSARY) if s["term_id"]}
    return out


# ── 구간 규칙 ────────────────────────────────────────


def test_poc1_10_segments_rebuild_original_all_samples():
    """원문은 한 글자도 바뀌지 않는다."""
    for r in SAMPLES:
        for f in r["payload"]["findings"]:
            assert "".join(s["text"] for s in annotate(f["text"], GLOSSARY)) == f["text"], (r["result_id"], f["id"])


def test_poc1_10_longest_match_first():
    """'준임상 수준' 안의 '임상 수준'을 전문 상담 권고 범위로 잘못 잇지 않는다 (회귀)."""
    segs = annotate("4개 영역에서 준임상 수준(60–69T)의 상승", GLOSSARY)
    assert ("준임상 수준", "term.range_borderline") in {(s["text"], s["term_id"]) for s in segs}
    assert "term.range_clinical" not in term_ids(segs)
    assert ("60–69T", "term.notation_t") in {(s["text"], s["term_id"]) for s in segs}


def test_poc1_10_same_term_only_first_occurrence():
    segs = annotate("상승된 양상, 다시 상승", GLOSSARY)
    assert term_ids(segs).count("term.elevated") == 1
    assert segs[0] == {"text": "상승", "term_id": "term.elevated"}


def test_poc1_10_no_match_single_segment():
    assert annotate("친구들과 잘 어울리지 못하는 것 같아요.", GLOSSARY) == \
        [{"text": "친구들과 잘 어울리지 못하는 것 같아요.", "term_id": None}]


def test_poc1_10_base_sample_targets_linked():
    linked = _linked([BASE["payload"]])
    assert [t for t in BASE_TARGETS if t not in linked] == []


@pytest.mark.skipif(not PRIVATE, reason="data/private/kcbcl_results/ 없음 (커밋하지 않는 데이터)")
def test_poc1_10_private_report_targets_linked():
    linked = _linked([json.loads(p.read_text(encoding="utf-8"))["payload"] for p in PRIVATE])
    assert [t for t in PRIVATE_TARGETS if t not in linked] == []


def test_poc1_10_interpretive_kinds():
    assert all(BY_ID[i]["kind"] == "interpretive" for i in INTERPRETIVE)
    assert all(g["status"] == "draft" for g in GLOSSARY)


# 풀이에 쓰지 않는 평가·완화 표현 (spec 7장, G-01). 금칙 사전(PoC1-08)이 잡지 않는 것만 둔다.
NON_NEUTRAL = ["뜻은 아닙니다", "아닙니다", "정해졌", "정해진", "다행", "좋은", "나쁜"]


def test_poc1_10_glossary_plain_is_neutral():
    """G-01 (2026-10-05): 풀이는 객관적인 뜻만. 긍정·부정 평가와 완화 문구를 쓰지 않는다."""
    bad = [(g["id"], w) for g in GLOSSARY for w in NON_NEUTRAL if w in g["plain"]]
    assert bad == []


def test_poc1_10_syndrome_names_not_cut_by_glossary():
    """증후군 척도 이름은 점수 블록과 카드가 설명한다. 용어사전 표현이 그 이름 안에 걸리지 않는다
    (예: '미성숙'이 '사회적 미성숙'을 자르지 않게 '미성숙한 행동'으로 둔다)."""
    syndromes = {s["name"] for s in BASE["payload"]["scores"] if DEF["scales"].get(s["scale"], {}).get("group") == "syndrome"}
    words = {w for g in GLOSSARY for w in [g["term"], *g["aliases"]]}
    assert [(w, n) for w in words for n in syndromes if w in n] == []


def test_poc1_10_view_attaches_segments():
    view = results.build_view(BASE["payload"], DEF, content.load_scale_cards(), content.load_summary_templates(),
                              content.load_phrases(), GLOSSARY)
    blocks = [b for s in view["sections"] for b in s["blocks"] if b["kind"] == "finding"]
    socimm = next(b for b in blocks if b["id"] == "V.socimm")
    assert "term.notation_percentile" in term_ids(socimm["segments"])


# ── 용어사전 형식 ────────────────────────────────────


@pytest.mark.parametrize("fn", [
    lambda es: [{**es[0], "kind": "other"}, *es[1:]],                          # 알 수 없는 kind
    lambda es: [{k: v for k, v in es[0].items() if k != "status"}, *es[1:]],   # 필수 필드 누락
    lambda es: [{**es[0], "patterns": ["(T"]}, *es[1:]],                       # 깨진 정규식
    lambda es: [{**es[0], "plain": "{t}점"}, *es[1:]],                         # 자리표시자
], ids=["kind", "missing", "regex", "placeholder"])
def test_glossary_rejects_bad_format(content_copy, fn):  # noqa: F811
    _edit(content_copy, "glossary.json", fn)
    with pytest.raises(ContentError):
        content.load_glossary(content_copy)


def test_poc1_08_glossary_scan_is_plain_only():
    """찾기 표현(term·aliases)은 보고서 원문 낱말이라 검사하지 않고, 풀이 문장만 검사한다."""
    where = {w for f, w, _ in content.iter_content_sentences() if f == "glossary.json"}
    assert "term.worsening.plain[0]" in where
    assert not any(w.endswith(".term[0]") for w in where)


# ── PoC1-11 상담 질문으로 저장 ───────────────────────


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "bridge.db"
    db.init(path)
    conn = db.connect(path)
    ctx = pipeline.load_context(conn, BASE["result_id"])
    yield conn, ctx
    conn.close()


def test_poc1_11_save_report_phrase(setup):
    conn, ctx = setup
    since = conn.execute("SELECT COALESCE(MAX(turn_id), 0) FROM qa_turns").fetchone()[0]
    notes.save_report_phrase(conn, ctx.child_id, "VI.p3", BY_ID["term.developmental_transition"], ctx.phrases)
    turn = conn.execute("SELECT * FROM qa_turns WHERE turn_id > ?", (since,)).fetchone()
    assert (turn["route"], turn["intent"], turn["saved_to_note"]) == ("note", None, 1)
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0          # LLM 없음
    [note] = notes.list_notes(conn, ctx.child_id, since)
    assert note["text"] == "보고서의 '발달적 전이' 표현이 무슨 뜻인지 궁금합니다."
    assert (note["type"], note["related_refs"]) == ("report_phrase", ["VI.p3", "term.developmental_transition"])
    assert note["source_turn_id"] == turn["turn_id"]


def test_poc1_11_saved_phrase_goes_into_brief(setup):
    conn, ctx = setup
    since = conn.execute("SELECT COALESCE(MAX(turn_id), 0) FROM qa_turns").fetchone()[0]
    notes.save_report_phrase(conn, ctx.child_id, "VI.p3", BY_ID["term.developmental_transition"], ctx.phrases)
    items = notes.list_notes(conn, ctx.child_id, since)
    text = brief.build_brief(ctx, notes.skipped(items), brief.answered_turns(conn, ctx.child_id, since),
                             brief.crisis_turns(conn, ctx.child_id, since))
    assert "[결과·용어 이해]" in text
    assert "'발달적 전이' 표현" in text
    assert "VI.p3" in text and "term.developmental_transition · 발달적 전이" in text
