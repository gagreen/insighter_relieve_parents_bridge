"""진단명 사전·금칙 표현 검사 [G-01, G-06].

콘텐츠 사전 검사(PoC1-08)와 AI 응답 출력 검증(PoC2-08)에 같은 목록을 쓴다.
'진단'·'치료' 같은 단어 자체는 경계 안내에 필요하므로 막지 않고, 이름과 권고·판단 형태만 막는다.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from bridge import config

CATEGORIES = {
    "diagnosis_name", "diagnosis_possibility", "treatment", "medication",
    "institution", "prognosis", "reassurance", "threat",
}


@dataclass(frozen=True)
class GuardTerm:
    id: str
    pattern: str
    type: str
    category: str
    regex: re.Pattern


@dataclass(frozen=True)
class Violation:
    term_id: str
    category: str
    matched: str


def load_guard_terms(path: Path | None = None) -> list[GuardTerm]:
    path = path or config.CONTENT_DIR / "guard_terms.json"
    terms = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        if item["category"] not in CATEGORIES:
            raise ValueError(f"{item['id']}: 알 수 없는 category {item['category']!r}")
        if item["type"] == "literal":
            source = re.escape(item["pattern"])
        elif item["type"] == "regex":
            source = item["pattern"]
        else:
            raise ValueError(f"{item['id']}: 알 수 없는 type {item['type']!r}")
        try:
            regex = re.compile(source, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"{item['id']}: 잘못된 정규식 {item['pattern']!r} ({e})") from e
        terms.append(GuardTerm(item["id"], item["pattern"], item["type"], item["category"], regex))
    return terms


def find_violations(text: str, terms: list[GuardTerm]) -> list[Violation]:
    """원문과 공백을 지운 문장 양쪽에서 찾는다("주의력 결핍" → "주의력결핍")."""
    variants = (text, re.sub(r"\s+", "", text))
    found = []
    for term in terms:
        for variant in variants:
            if m := term.regex.search(variant):
                found.append(Violation(term.id, term.category, m.group(0)))
                break
    return found
