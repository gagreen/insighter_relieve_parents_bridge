"""PoC2-02 마스킹 [G-09].

외부 API로 보내거나 저장하는 질문은 이 모듈을 거친 문장만 쓴다. subjects(식별 정보)를 읽는 유일한 모듈이다
(2026-10-04 결정). 패턴 세부와 범위 밖 항목은 specs/poc.md PoC2-02.
"""
import re
import sqlite3
from dataclasses import dataclass

from bridge import db

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


def _name_patterns(child_name: str) -> list[re.Pattern]:
    names = [child_name]
    if len(child_name) >= _MIN_NAME_LEN_FOR_GIVEN:
        names.append(child_name[1:])
    # 앞에 한글이 붙은 경우는 다른 낱말의 일부로 본다. 뒤의 조사·호격("이가", "아")은 남긴다.
    return [re.compile(rf"(?<![가-힣]){re.escape(n)}") for n in names]


def mask(text: str, child_name: str) -> MaskResult:
    counts = {}
    text, counts["email"] = _EMAIL.subn(CONTACT_TOKEN, text)
    text, counts["phone"] = _PHONE.subn(CONTACT_TOKEN, text)
    text, counts["school"] = _SCHOOL.subn(SCHOOL_TOKEN, text)
    counts["name"] = 0
    for pattern in _name_patterns(child_name):
        text, n = pattern.subn(NAME_TOKEN, text)
        counts["name"] += n
    return MaskResult(text, {k: counts[k] for k in ("name", "school", "phone", "email")})


def mask_for_child(conn: sqlite3.Connection, child_id: str, text: str) -> MaskResult:
    return mask(text, db.get_subject(conn, child_id)["name"])
