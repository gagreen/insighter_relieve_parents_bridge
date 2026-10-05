"""키워드 패턴 컴파일·검색 (위기 키워드 PoC2-03, 의도 키워드 PoC2-04).

content/의 패턴 항목 {id, pattern, type: literal | regex, ...}을 다룬다. literal은 대소문자를 무시한다.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pattern:
    id: str
    type: str
    regex: re.Pattern
    meta: dict = field(default_factory=dict)  # category 등 나머지 필드


def compile_patterns(items: list[dict], where: str) -> list[Pattern]:
    """잘못된 type이나 정규식이면 ValueError."""
    out = []
    for item in items:
        pid = item.get("id", "?")
        if item.get("type") == "literal":
            source = re.escape(item["pattern"])
        elif item.get("type") == "regex":
            source = item["pattern"]
        else:
            raise ValueError(f"{where}.{pid}: 알 수 없는 type {item.get('type')!r}")
        try:
            regex = re.compile(source, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"{where}.{pid}: 잘못된 정규식 {item['pattern']!r} ({e})") from e
        meta = {k: v for k, v in item.items() if k not in ("id", "pattern", "type")}
        out.append(Pattern(pid, item["type"], regex, meta))
    return out


def matched(text: str, patterns: list[Pattern]) -> list[Pattern]:
    """원문과 공백을 지운 문장 양쪽에서 찾는다("죽고 싶" / "죽고싶")."""
    variants = (text, re.sub(r"\s+", "", text))
    return [p for p in patterns if any(p.regex.search(v) for v in variants)]
