"""PoC2-05 안전 응답 조립, 척도 찾기 [G-01, G-03, G-04, G-05, G-12] + spec 1-1 R-2."""
import copy
import dataclasses
import re

import pytest

from bridge import config, pipeline
from bridge.guard.output import numbers_in
from bridge.guard.terms import find_violations, load_guard_terms

TERMS = load_guard_terms()
KINDS = ["diagnosis", "parenting", "low_confidence", "guard_fallback"]


@pytest.fixture(scope="module")
def ctx(loaded_db):
    return pipeline.load_context(loaded_db, "R-KCBCL_4_17-035")


def _score(ctx, scale):
    return next(i for i in ctx.view["items"] if i["scale"] == scale)


def _template(ctx, kind):
    return next(t for t in ctx.safe_responses if t["kind"] == kind)


def _first_line(ctx, finding_id):
    return next(f for f in ctx.payload["findings"] if f["id"] == finding_id)["text"].split("\n")[0].strip()


def _fact(ctx, item):
    return ctx.phrases["safe_scale_fact"].format(scale_name=item["name"], t=item["t"], range_label=item["range_label"])


def _numbers(text):
    return re.findall(r"\d+", text)


def test_poc2_05_spec_example_adhd(ctx):
    """공감 → 척도 사실 → 보고서 인용 → 본문 → 선별 검사 안내 → note_saved → 준비 행동 (spec PoC2-05 순서)."""
    text, refs = pipeline.safe_response("diagnosis", "ADHD인가요?", ctx)
    att = _score(ctx, "attention")
    quote = _first_line(ctx, "V.attention")
    t = _template(ctx, "diagnosis")
    parts = [t["empathy"], _fact(ctx, att), ctx.phrases["safe_report_quote"].format(quote=quote), t["body"],
             ctx.phrases["screening_note"], ctx.phrases["note_saved"], t["closing"]]
    assert text == " ".join(parts)
    assert refs == [att["id"], "V.attention"]                    # 근거 칩: 척도 + 인용한 서술


def test_g03_safe_response_numbers_come_from_payload(ctx):
    text, _ = pipeline.safe_response("diagnosis", "ADHD인가요?", ctx)
    allowed = {str(_score(ctx, "attention")["t"])} | set(numbers_in(_first_line(ctx, "V.attention")))
    assert set(_numbers(text)) <= allowed


def test_poc2_05_scale_named_in_question(ctx):
    text, _ = pipeline.safe_response("diagnosis", "공격성 점수가 심각한가요?", ctx)
    agg = _score(ctx, "aggressive")
    assert _fact(ctx, agg) in text


def test_poc2_05_all_found_scales_are_stated(ctx):
    """질문에 척도가 둘이면 둘 다 사실 문장으로 넣는다. 관찰 소견이 없는 척도는 인용 없이."""
    text, refs = pipeline.safe_response("diagnosis", "위축과 우울/불안이 커질까요?", ctx)
    wd, ad = _score(ctx, "withdrawn"), _score(ctx, "anxdep")
    assert _fact(ctx, wd) in text and _fact(ctx, ad) in text
    assert text.index(_fact(ctx, wd)) < text.index(_fact(ctx, ad))      # payload 순서
    assert "보고서에는" not in text                                      # 035에는 위축 관찰 소견이 없음
    assert refs == [wd["id"], ad["id"]]


def test_poc2_05_scale_count_is_capped(ctx):
    question = "사회적 미성숙, 주의집중 문제, 공격성, 위축이 다 심각한가요?"
    text, _ = pipeline.safe_response("diagnosis", question, ctx)
    found = [i for i in pipeline.find_scales(question, ctx) if i["t"] is not None and i["range_label"]]
    assert len(found) > config.SAFE_MAX_SCALES
    stated = [i for i in found if _fact(ctx, i) in text]
    assert stated == found[:config.SAFE_MAX_SCALES]


def test_poc2_05_quote_with_guard_term_is_dropped(ctx):
    """인용할 첫 줄이 금칙 표현에 걸리면 인용하지 않는다(B-4)."""
    payload = copy.deepcopy(ctx.payload)
    finding = next(f for f in payload["findings"] if f["id"] == "V.attention")
    finding["text"] = "앞으로 악화될 가능성이 높음\n둘째 줄"
    text, refs = pipeline.safe_response("diagnosis", "ADHD인가요?", dataclasses.replace(ctx, payload=payload))
    assert "보고서에는" not in text and "V.attention" not in refs
    assert find_violations(text, TERMS) == []


def test_find_scales_name_match_wins_over_terms(ctx):
    """'정서불안정'은 이름 일치. 이름에 들어 있는 '불안'은 표현으로 다시 찾지 않는다. '우울'로는 찾는다."""
    found = pipeline.find_scales("정서불안정이 우울증인가요?", ctx)
    assert [f["scale"] for f in found] == ["emotional_instability", "anxdep"]


def test_find_scales_term_inside_matched_name_is_ignored(ctx):
    assert [f["scale"] for f in pipeline.find_scales("정서불안정이 뭔가요?", ctx)] == ["emotional_instability"]


def test_find_scales_ignores_spaces(ctx):
    assert pipeline.find_scales("주의집중문제가 뭔가요", ctx)[0]["scale"] == "attention"


@pytest.mark.parametrize("question", [
    "자폐인가요?",                     # 척도를 찾지 못함
    "성문제가 걱정돼요",               # 미실시 척도
    "정서불안정이 심한가요?",          # 판정 기준 없는 척도 (범위 이름 없음)
])
def test_poc2_05_no_facts_without_usable_scale(ctx, question):
    text, _ = pipeline.safe_response("diagnosis", question, ctx)
    assert _numbers(text) == [] and "보고서에는" not in text


@pytest.mark.parametrize("kind", KINDS)
def test_r2_safe_responses_say_note_saved(ctx, kind):
    text, _ = pipeline.safe_response(kind, "ADHD인가요?", ctx)
    assert ctx.phrases["note_saved"] in text


@pytest.mark.parametrize("kind", KINDS)
def test_poc2_05_empathy_first_and_screening_only_for_diagnosis(ctx, kind):
    text, _ = pipeline.safe_response(kind, "질문", ctx)
    t = _template(ctx, kind)
    if t["empathy"]:
        assert text.startswith(t["empathy"])
    assert (ctx.phrases["screening_note"] in text) == (kind == "diagnosis")
    assert text.endswith(t["closing"])


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("question", ["ADHD인가요?", "질문", "사회적 미성숙과 공격성, 주의집중 문제가 걱정돼요"])
def test_b4_safe_responses_pass_guard(ctx, kind, question):
    text, _ = pipeline.safe_response(kind, question, ctx)
    assert text and find_violations(text, TERMS) == []


def test_poc2_05_number_josa_is_grammatical(ctx):
    text, _ = pipeline.safe_response("diagnosis", "ADHD인가요?", ctx)
    assert "T점수 66점으로" in text and "66로" not in text
