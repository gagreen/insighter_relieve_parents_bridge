"""PoC2-04 의도 분류 1차: 키워드 규칙.

의도가 정해지지 않으면(intent=None) 파이프라인이 LLM 2차 분류로 넘긴다. 위기는 crisis.py가 먼저 본다.
키워드는 모든 검사가 공유하므로 척도 이름을 넣지 않는다(G-12).
"""
from dataclasses import dataclass
from functools import lru_cache

from bridge import content
from bridge.content import INTENT_KEYWORD_KEYS as KEYWORD_INTENTS
from bridge.rules.patterns import Pattern, compile_patterns, matched

# 진단 신호가 있으면 다른 의도와 겹쳐도 LLM에 맡기지 않는다 (spec PoC2-04, 2026-10-04 결정)
PRIORITY_INTENT = "diagnosis"


@dataclass(frozen=True)
class KeywordIntent:
    intent: str | None             # 정해진 의도, 없으면 LLM 2차로
    hits: dict[str, list[str]]     # 의도 → 걸린 keyword id (걸린 의도만)


def _compile(keywords: dict[str, list[dict]]) -> dict[str, list[Pattern]]:
    return {intent: compile_patterns(keywords[intent], f"intent.{intent}") for intent in KEYWORD_INTENTS}


@lru_cache(maxsize=1)
def _default_patterns() -> dict[str, list[Pattern]]:
    return _compile(content.load_intent_keywords())


def classify_by_keywords(masked_text: str, keywords: dict | None = None) -> KeywordIntent:
    """diagnosis가 걸리면 diagnosis, 그 밖에는 정확히 한 의도만 걸릴 때 그 의도, 아니면 None."""
    patterns = _default_patterns() if keywords is None else _compile(keywords)
    hits = {}
    for intent in KEYWORD_INTENTS:
        if found := matched(masked_text, patterns[intent]):
            hits[intent] = [p.id for p in found]
    if PRIORITY_INTENT in hits:
        intent = PRIORITY_INTENT
    elif len(hits) == 1:
        intent = next(iter(hits))
    else:
        intent = None
    return KeywordIntent(intent, hits)
