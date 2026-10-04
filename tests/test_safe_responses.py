"""PoC2-05 안전 응답, 척도 찾기 [G-01, G-03, G-05, G-12]."""
import re

import pytest

from bridge import pipeline
from bridge.guard.terms import find_violations, load_guard_terms

TERMS = load_guard_terms()


@pytest.fixture(scope="module")
def ctx(loaded_db):
    return pipeline.load_context(loaded_db, "R-KCBCL_4_17-035")


def _score(ctx, scale):
    return next(i for i in ctx.view["items"] if i["scale"] == scale)


def _numbers(text):
    return re.findall(r"\d+", text)


def test_poc2_05_spec_example_adhd(ctx):
    text, refs = pipeline.safe_response("diagnosis", "ADHD인가요?", ctx)
    att = _score(ctx, "attention")
    assert att["name"] in text and str(att["t"]) in text and att["range_label"] in text
    assert _numbers(text) == [str(att["t"])]          # G-03: 숫자는 payload 값만
    assert refs == [att["id"]]


def test_poc2_05_scale_named_in_question(ctx):
    text, _ = pipeline.safe_response("diagnosis", "공격성 점수가 심각한가요?", ctx)
    agg = _score(ctx, "aggressive")
    assert agg["name"] in text and str(agg["t"]) in text


def test_find_scales_name_match_wins_over_terms(ctx):
    """'정서불안정'은 이름 일치. 이름에 들어 있는 '불안'(불안/우울 표현)보다 앞선다."""
    found = pipeline.find_scales("정서불안정이 우울증인가요?", ctx)
    assert found[0]["scale"] == "emotional_instability"
    assert "anxdep" in [f["scale"] for f in found]


def test_find_scales_ignores_spaces(ctx):
    assert pipeline.find_scales("주의집중문제가 뭔가요", ctx)[0]["scale"] == "attention"


@pytest.mark.parametrize("question", [
    "자폐인가요?",                     # 척도를 찾지 못함
    "성문제가 걱정돼요",               # 미실시 척도
    "정서불안정이 우울증인가요?",      # 판정 기준 없는 척도 (범위 이름 없음)
])
def test_poc2_05_general_template_without_usable_scale(ctx, question):
    text, _ = pipeline.safe_response("diagnosis", question, ctx)
    assert _numbers(text) == []


@pytest.mark.parametrize("kind", ["diagnosis", "parenting", "low_confidence", "guard_fallback"])
@pytest.mark.parametrize("question", ["ADHD인가요?", "질문"])
def test_b4_safe_responses_pass_guard(ctx, kind, question):
    text, _ = pipeline.safe_response(kind, question, ctx)
    assert text and find_violations(text, TERMS) == []
