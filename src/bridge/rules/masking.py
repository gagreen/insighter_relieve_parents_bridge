"""PoC2-02 마스킹 [G-09].

외부 API로 보내거나 저장하는 질문은 이 모듈을 거친 문장만 쓴다. subjects(식별 정보)를 읽는 유일한 모듈이다
(2026-10-04 결정). 패턴 세부와 범위 밖 항목은 specs/poc.md PoC2-02.
"""
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from bridge import content, db

NAME_TOKEN = "[이름]"
SCHOOL_TOKEN = "[학교]"
CONTACT_TOKEN = "[연락처]"

# \w는 한글도 잡아 앞 낱말("이메일은abc@…")까지 먹으므로 ASCII로 한정한다.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# 휴대폰은 구분자 선택, 일반전화는 구분자 필수. 구분자 없는 숫자(T점수·백분위·날짜)는 건드리지 않는다(G-03).
_PHONE = re.compile(r"(?<!\d)(?:01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4})(?!\d)")
# 붙여 쓴 정식 이름만. 줄임말("○○초")·띄어 쓴 이름은 일반 문장과 구분되지 않는다.
_SCHOOL = re.compile(r"[가-힣A-Za-z0-9○◯●*]+(?:초등학교|중학교|고등학교)")
_MIN_NAME_LEN_FOR_GIVEN = 3  # 성을 뺀 이름을 쓰는 최소 길이 (복성 미지원)


@dataclass(frozen=True)
class MaskResult:
    text: str
    counts: dict[str, int]  # {"name", "school", "phone", "email"}: 바꾼 횟수


def _name_pattern(name: str) -> re.Pattern:
    # 앞에 한글이 붙은 경우는 다른 낱말의 일부로 본다. 뒤의 조사·호격("이가", "아")은 남긴다.
    return re.compile(rf"(?<![가-힣]){re.escape(name)}")


@lru_cache(maxsize=1)
def _default_exceptions() -> tuple[dict, ...]:
    return tuple(content.load_name_word_exceptions())


def _keep_spans(text: str, given: str, exceptions) -> list[tuple[int, int]]:
    """성을 뺀 이름이 일반 낱말과 같을 때, 낱말 용법 패턴에 걸린 범위 (PoC2-02, 2026-10-05)."""
    entry = next((e for e in exceptions if e["word"] == given), None)
    if entry is None:
        return []
    return [m.span() for p in entry["keep_patterns"] for m in re.finditer(p, text)]


def mask(text: str, child_name: str, exceptions: list[dict] | None = None) -> MaskResult:
    """전체 이름은 항상 가린다. 성을 뺀 이름은 낱말 용법이 분명한 자리만 남기고 가린다."""
    exceptions = _default_exceptions() if exceptions is None else exceptions
    counts = {}
    text, counts["email"] = _EMAIL.subn(CONTACT_TOKEN, text)
    text, counts["phone"] = _PHONE.subn(CONTACT_TOKEN, text)
    text, counts["school"] = _SCHOOL.subn(SCHOOL_TOKEN, text)
    text, counts["name"] = _name_pattern(child_name).subn(NAME_TOKEN, text)
    if len(child_name) >= _MIN_NAME_LEN_FOR_GIVEN:
        given = child_name[1:]
        keep = _keep_spans(text, given, exceptions)
        out, last = [], 0
        for m in _name_pattern(given).finditer(text):
            if any(s <= m.start() and m.end() <= e for s, e in keep):
                continue
            out += [text[last:m.start()], NAME_TOKEN]
            last = m.end()
            counts["name"] += 1
        text = "".join(out) + text[last:]
    return MaskResult(text, {k: counts[k] for k in ("name", "school", "phone", "email")})


def mask_for_child(conn: sqlite3.Connection, child_id: str, text: str) -> MaskResult:
    return mask(text, db.get_subject(conn, child_id)["name"])
