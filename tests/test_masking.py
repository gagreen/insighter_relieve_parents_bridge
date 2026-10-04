"""PoC2-02 마스킹 [G-09]."""
import re

import pytest

from bridge import config
from bridge.rules.masking import mask, mask_for_child

NAME = "백재원"  # 기준 샘플 035의 가상 이름 (spec 2-3, PoC2-02)


def test_poc2_02_spec_example():
    r = mask("재원이가 ○○초등학교에서 010-1234-5678로 연락이 왔어요", NAME)
    assert r.text == "[이름]이가 [학교]에서 [연락처]로 연락이 왔어요"
    assert r.counts == {"name": 1, "school": 1, "phone": 1, "email": 0}


@pytest.mark.parametrize("text, expected", [
    ("백재원 보호자입니다", "[이름] 보호자입니다"),
    ("재원아 하고 불러도 대답을 안 해요", "[이름]아 하고 불러도 대답을 안 해요"),
    ("재원이는 집중을 못 해요", "[이름]이는 집중을 못 해요"),
    ("재원를 데리고 갔어요", "[이름]를 데리고 갔어요"),
    ("우리 재원이, 재원이가요", "우리 [이름]이, [이름]이가요"),
])
def test_poc2_02_name_forms(text, expected):
    assert mask(text, NAME).text == expected


def test_poc2_02_name_inside_hangul_word_is_kept():
    assert mask("단지우유를 좋아해요", "김지우").text == "단지우유를 좋아해요"


def test_poc2_02_short_name_masks_full_name_only():
    """2글자 이름에서 1글자 이름만 바꾸면 문장이 망가진다 (복성 미지원)."""
    assert mask("김윤 보호자예요. 윤리 문제는 아니고요", "김윤").text == "[이름] 보호자예요. 윤리 문제는 아니고요"


@pytest.mark.parametrize("text, expected", [
    ("한빛중학교 2학년 형이 있어요", "[학교] 2학년 형이 있어요"),
    ("OO고등학교 근처예요", "[학교] 근처예요"),
    ("아이가 다니는 초등학교에서 연락이 왔어요", "아이가 다니는 초등학교에서 연락이 왔어요"),
    ("수업 중에 돌아다녀요", "수업 중에 돌아다녀요"),
])
def test_poc2_02_school(text, expected):
    assert mask(text, NAME).text == expected


@pytest.mark.parametrize("text", [
    "01012345678로 주세요", "010 1234 5678로 주세요", "011-123-4567로 주세요", "02-123-4567로 주세요",
])
def test_poc2_02_phone(text):
    assert mask(text, NAME).text == "[연락처]로 주세요"


def test_poc2_02_email():
    assert mask("parent.kim+1@example.co.kr 로 보내 주세요", NAME).text == "[연락처] 로 보내 주세요"


def test_poc2_02_scores_in_question_are_kept():
    """G-03: 질문 속 숫자는 나중에 대조할 수 있도록 남긴다."""
    text = "주의집중 문제가 66점이고 백분위 95면요? 2026-04-10 검사예요"
    assert mask(text, NAME).text == text


def test_poc2_02_text_without_identifiers_is_unchanged():
    r = mask("T점수가 무슨 뜻이에요?", NAME)
    assert r.text == "T점수가 무슨 뜻이에요?"
    assert set(r.counts.values()) == {0}


def test_poc2_02_mask_for_child_reads_subjects(loaded_db):
    assert mask_for_child(loaded_db, "C-035", "재원이가 걱정돼요").text == "[이름]이가 걱정돼요"


def test_g09_only_masking_reads_subjects():
    """2026-10-04 결정: subjects(식별 정보)는 db.py와 마스킹 모듈만 읽는다."""
    src = config.ROOT / "src" / "bridge"
    pattern = re.compile(r"get_subject\(|(FROM|JOIN)\s+subjects", re.IGNORECASE)
    readers = {p.relative_to(src).as_posix() for p in src.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))}
    assert readers <= {"db.py", "rules/masking.py"}
    assert "rules/masking.py" in readers
