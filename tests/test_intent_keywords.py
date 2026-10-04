"""PoC2-04 의도 분류 1차(키워드)."""
import inspect

import pytest

from bridge.guard.terms import load_guard_terms
from bridge.rules.intents import classify_by_keywords


@pytest.mark.parametrize("text, intent", [
    ("ADHD인가요?", "diagnosis"),
    ("병원에 가 봐야 할까요?", "diagnosis"),
    ("커서 좋아질까요?", "diagnosis"),
    ("정상인가요?", "diagnosis"),
    ("아이를 어떻게 훈육해야 하나요?", "parenting"),
    ("상담 예약을 바꾸고 싶어요", "out_of_scope"),
    ("결제 영수증은 어디서 받나요?", "out_of_scope"),
    ("T점수가 무슨 뜻이에요?", "explain"),
    ("상위 약 5%가 무슨 뜻이에요?", "explain"),   # '약'이 약물 키워드에 걸리지 않는다
    ("관찰 권고 범위가 뭐예요?", "explain"),
])
def test_poc2_04_single_intent_by_keywords(text, intent):
    r = classify_by_keywords(text)
    assert r.intent == intent
    assert list(r.hits) == [intent]


def test_poc2_04_diagnosis_wins_over_other_intents():
    """2026-10-04 결정: diagnosis 키워드가 걸리면 다른 의도와 겹쳐도 diagnosis."""
    r = classify_by_keywords("ADHD가 뭐예요?")
    assert r.intent == "diagnosis"
    assert {"diagnosis", "explain"} <= set(r.hits)


def test_poc2_04_multiple_intents_without_diagnosis_go_to_llm():
    r = classify_by_keywords("상담 예약은 어떻게 해야 하나요?")
    assert r.intent is None
    assert {"parenting", "out_of_scope"} <= set(r.hits)


def test_poc2_04_no_keyword_goes_to_llm():
    r = classify_by_keywords("요즘 밤에 잠을 잘 못 자요")
    assert (r.intent, r.hits) == (None, {})


# guard_terms의 regex 진단명은 표현이 정해져 있지 않아 예시 문자열을 둔다. 새 regex 진단명을 넣으면 여기에도 추가한다.
REGEX_DIAGNOSIS_SAMPLES = {"guard.dx.002": "ADD", "guard.dx.011": "틱", "guard.dx.012": "투렛"}


@pytest.mark.parametrize("term", [t for t in load_guard_terms() if t.category == "diagnosis_name"], ids=lambda t: t.id)
def test_poc2_04_guard_diagnosis_names_are_diagnosis_keywords(term):
    """진단명 사전과 의도 키워드가 따로 놀지 않게 한다 (content/README.md)."""
    sample = term.pattern if term.type == "literal" else REGEX_DIAGNOSIS_SAMPLES[term.id]
    assert "diagnosis" in classify_by_keywords(f"혹시 {sample} 아닌가요?").hits


def test_poc2_04_keyword_classification_does_not_take_scores():
    """G-02: 의도 1차 분류는 질문 텍스트만 본다."""
    assert list(inspect.signature(classify_by_keywords).parameters) == ["masked_text", "keywords"]
