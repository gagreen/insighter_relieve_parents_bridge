"""PoC2-03 위기 감지 1차(키워드) [G-05] → B-5."""
import inspect

import pytest

from bridge.rules.crisis import detect_crisis


@pytest.mark.parametrize("text", [
    "아이가 죽고 싶다고 해요",
    "[이름]이가 죽고싶대요",
    "손목을 그었어요",
    "자해한 흔적이 있어요",
    "남편이 아이를 때려요",
    "저도 살기 싫어요",
    "사라지고 싶다는 말을 자주 해요",
])
def test_poc2_03_crisis_expressions_are_detected(text):
    assert detect_crisis(text)


def test_poc2_03_caregiver_distress_category():
    hits = detect_crisis("제가 아이를 때릴 것 같아요")
    assert "caregiver_distress" in {h.category for h in hits}


@pytest.mark.parametrize("text", [
    "힘들어 죽겠어요",                      # 관용어 (2026-10-04 결정)
    "공격성 점수가 높은데 친구를 때려요",   # 공격성 척도 행동
    "같은 반 남자아이를 때렸어요",
    "수업 시간에 가만히 못 견뎌요",
    "주의집중 문제가 뭐예요?",
    "죽고 사는 문제는 아니지만 궁금해요",
])
def test_poc2_03_non_crisis_expressions_are_not_detected(text):
    assert detect_crisis(text) == []


def test_poc2_03_crisis_does_not_take_scores():
    """G-02 / spec 2-3: 위기 1차 감지는 질문 텍스트만 본다."""
    assert list(inspect.signature(detect_crisis).parameters) == ["masked_text", "crisis"]
