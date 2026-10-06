"""평가 데이터 파일 검증 [specs/poc.md 6-1·6-2, eval/README.md]. LLM을 부르지 않는다."""
import json

import pytest

from bridge import config, pipeline
from bridge.rules.crisis import detect_crisis
from bridge.rules.intents import classify_by_keywords
from eval import run


@pytest.fixture(scope="module")
def ctx(loaded_db):
    return pipeline.load_context(loaded_db, run.BASE_RESULT_ID)


@pytest.fixture(scope="module")
def items():
    return run.load_items()


@pytest.fixture(scope="module")
def templates():
    return run.load_templates()


def _keyword_route(text: str) -> str | None:
    """키워드 규칙만으로 정해지는 경로. LLM 분류로 넘어가면 None."""
    if detect_crisis(text):
        return "crisis"
    kw = classify_by_keywords(text)
    return config.ROUTE_BY_INTENT[kw.intent] if kw.intent else None


# ── 기준 평가셋 (6-1) ───────────────────────────────


def test_6_1_question_set_composition(items, ctx):
    """40문항 15/15/5/5, 태그 하한(인젝션 2, 권고 행동 3, 답 없음 2, 양육 3, 걱정 질문), 근거 id 존재."""
    assert run.check_composition(items, ctx.pack) == []
    assert len(items) == 40


def test_6_1_keyword_decided_items_match_expected_route(items):
    """키워드 규칙으로 경로가 정해지는 문항은 그 경로가 기대 경로와 같다(문항 작성 실수 방지)."""
    wrong = [(i.id, r) for i in items if (r := _keyword_route(i.question)) and r != i.expected_route]
    assert wrong == []


def test_6_1_indirect_items_reach_llm_classification(items):
    """`indirect` 문항은 키워드에 걸리지 않아 LLM 분류를 시험한다."""
    assert [i.id for i in items if "indirect" in i.tags and _keyword_route(i.question)] == []


# ── check_composition이 위반을 잡는지 ─────────────────


def _item(**kw):
    base = dict(id="X", type="explain", question="q", expected_route="answer", expected_evidence=[], tags=[], note="")
    return run.EvalItem(**{**base, **kw})


def test_6_1_composition_detects_violations(items, ctx):
    broken = [*items[1:], items[1]]                                    # 1문항 빠지고 id 중복
    broken.append(_item(id="Y", expected_route="safe"))                # 유형과 경로 불일치
    broken.append(_item(id="Z", tags=["unknown_tag"]))                 # 모르는 태그
    broken.append(_item(id="W", expected_evidence=["NO.SUCH.ID"]))     # 없는 근거 id
    errors = "\n".join(run.check_composition(broken, ctx.pack))
    for expected in ("유형별 문항 수", "id 중복", "Y", "Z", "NO.SUCH.ID"):
        assert expected in errors


# ── 다샘플 템플릿 (6-2) ─────────────────────────────


def test_6_2_templates_are_valid(templates):
    assert run.check_templates(templates) == []
    assert {t.type for t in templates} == {"explain", "diagnosis"}    # 위기형·범위 밖은 넣지 않음


def test_6_2_check_templates_detects_violations():
    bad = [
        run.Template("A", "crisis", None, "q", "crisis", [], ""),                          # 위기형 금지
        run.Template("B", "explain", "range:weird", "q", "answer", [], ""),                # 모르는 slot
        run.Template("C", "explain", None, "{scale_name}", "answer", [], ""),              # slot 없이 자리표시자
        run.Template("D", "explain", "not_administered", "{t}점", "answer", [], ""),        # 미실시에 {t}
        run.Template("E", "explain", "highest", "{child_name}", "answer", [], ""),         # 모르는 자리표시자
        run.Template("F", "explain", "attention", "{scale_name}", "answer", [], ""),       # 척도 키로 고르기(G-12)
    ]
    errors = "\n".join(run.check_templates(bad))
    for tid in "ABCDEF":
        assert f"{tid}:" in errors


def test_6_2_samples_file_matches_selection():
    """samples.json은 select_samples() 결과를 고정한 것이다(손으로 고치지 않음)."""
    saved = json.loads((config.EVAL_DIR / "samples.json").read_text(encoding="utf-8"))["samples"]
    assert saved == run.select_samples()


# ── 질문 정리 샘플 ──────────────────────────────────


def test_organize_samples_format():
    rows = [json.loads(line) for line in (config.EVAL_DIR / "organize_samples.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert set(r) == {"id", "saved_questions", "expected_items", "note"}
        assert r["saved_questions"] and all(isinstance(q, str) and q for q in r["saved_questions"])
        assert 1 <= r["expected_items"] <= len(r["saved_questions"])
