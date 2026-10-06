"""PoC2-04 의도 분류 1차: 키워드 규칙.

의도가 정해지지 않으면(intent=None) 파이프라인이 LLM 2차 분류로 넘긴다. 위기는 crisis.py가 먼저 본다.
키워드는 모든 검사가 공유하므로 척도 이름을 넣지 않는다(G-12).
"""
import re
from dataclasses import dataclass
from functools import lru_cache

from bridge import content
from bridge.content import INTENT_KEYWORD_KEYS as KEYWORD_INTENTS
from bridge.guard.terms import GuardTerm, load_guard_terms
from bridge.rules.glossary_match import annotate
from bridge.rules.patterns import Pattern, compile_patterns, matched

# 진단 신호가 있으면 다른 의도와 겹쳐도 LLM에 맡기지 않는다 (spec PoC2-04, 2026-10-04 결정)
PRIORITY_INTENT = "diagnosis"


@dataclass(frozen=True)
class KeywordIntent:
    intent: str | None             # 정해진 의도, 없으면 LLM 2차로
    hits: dict[str, list[str]]     # 의도 → 걸린 keyword id (걸린 의도만)


def _compile(keywords: dict[str, list[dict]]) -> dict[str, list[Pattern]]:
    return {key: compile_patterns(items, f"intent.{key}") for key, items in keywords.items()}


@lru_cache(maxsize=1)
def _default_patterns() -> dict[str, list[Pattern]]:
    return _compile(content.load_intent_keywords())


def classify_by_keywords(masked_text: str, keywords: dict | None = None) -> KeywordIntent:
    """diagnosis가 걸리면 diagnosis, 그 밖에는 정확히 한 의도만 걸릴 때 그 의도, 아니면 None."""
    patterns = _default_patterns() if keywords is None else _compile(keywords)
    hits = {}
    for intent in KEYWORD_INTENTS:
        if found := matched(masked_text, patterns.get(intent, [])):
            hits[intent] = [p.id for p in found]
    if PRIORITY_INTENT in hits:
        intent = PRIORITY_INTENT
    elif len(hits) == 1:
        intent = next(iter(hits))
    else:
        intent = None
    return KeywordIntent(intent, hits)


# ── 진단 우선의 예외 (spec PoC2-04, 2026-10-06) ──────

_CUT = "|"   # 지운 구간 표시. 공백을 지운 문장 검색(patterns.matched)에서 앞뒤 낱말이 붙지 않게 한다.
# 진단명 바로 뒤에서 아이를 판단하는 서술 ("ADHD인가요", "ADHD 같은데", "틱이 있어요", "ADHD 의심")
_NAME_PREDICATE = re.compile(r"\s*(인가|인지|일까|아닐까|아닌가|맞나|맞는|같아|같은|일\s*수|이에요|예요|이죠|죠"
                             r"|(이|가)?\s*(있|없|아니|맞|의심))")
# 아이를 가리키는 표현이 있으면 진단명 뜻 질문으로 보지 않는다
_CHILD_REFERENCE = re.compile(r"(우리|저희)\s*(아이|애|아들|딸)|\[이름\]|(?<![가-힣])(아이|애)(가|는|한테|에게)")


@lru_cache(maxsize=1)
def _default_glossary() -> tuple[dict, ...]:
    return tuple(content.load_glossary())


@lru_cache(maxsize=1)
def _default_names() -> tuple[GuardTerm, ...]:
    """진단명 = 출력 검증과 같은 사전의 diagnosis_name (G-01)."""
    return tuple(t for t in load_guard_terms() if t.category == "diagnosis_name")


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    out, pos = [], 0
    for start, end in sorted(spans):
        out.append(text[pos:max(pos, start)] + _CUT)
        pos = max(pos, end)
    return "".join(out) + text[pos:]


def _glossary_spans(text: str, glossary) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for seg in annotate(text, list(glossary)):
        if seg["term_id"]:
            spans.append((pos, pos + len(seg["text"])))
        pos += len(seg["text"])
    return spans


def diagnosis_subroute(masked_text: str, *, keywords: dict | None = None, glossary=None,
                       names=None) -> str | None:
    """diagnosis로 정해진 질문의 하위 경로: 'glossary'(낱말 뜻) | 'diagnosis_term'(진단명 뜻) | None(그대로 diagnosis).

    둘 다 뜻 묻기 표현이 있어야 하고, 표현을 지운 나머지에 diagnosis 키워드가 남으면 예외로 보지 않는다(보수적 기본값).
    """
    patterns = _default_patterns() if keywords is None else _compile(keywords)
    if not matched(masked_text, patterns.get("meaning", [])):
        return None
    dx = patterns[PRIORITY_INTENT]

    spans = _glossary_spans(masked_text, _default_glossary() if glossary is None else glossary)
    if spans and not matched(_cut(masked_text, spans), dx):
        return "glossary"

    names = _default_names() if names is None else names
    name_spans = [m.span() for t in names for m in t.regex.finditer(masked_text) if m.end() > m.start()]
    if not name_spans or _CHILD_REFERENCE.search(masked_text):
        return None
    if any(_NAME_PREDICATE.match(masked_text, end) for _, end in name_spans):
        return None
    return None if matched(_cut(masked_text, name_spans), dx) else "diagnosis_term"
