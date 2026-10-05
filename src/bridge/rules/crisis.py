"""PoC2-03 위기 감지 1차: 키워드 규칙 [G-05] → B-5.

질문 텍스트(마스킹 후)만 본다. 점수·범위는 조건으로 쓰지 않는다(G-02, spec 2-3).
위기 경로 처리(대화 중단, 안내 템플릿, crisis_flag, 알림 로그)는 파이프라인에서 한다.
"""
from dataclasses import dataclass
from functools import lru_cache

from bridge import content
from bridge.rules.patterns import Pattern, compile_patterns, matched


@dataclass(frozen=True)
class CrisisHit:
    keyword_id: str
    category: str  # child_safety | caregiver_distress


@lru_cache(maxsize=1)
def _default_patterns() -> tuple[Pattern, ...]:
    return tuple(compile_patterns(content.load_crisis()["keywords"], "crisis"))


def detect_crisis(masked_text: str, crisis: dict | None = None) -> list[CrisisHit]:
    """걸린 위기 키워드 목록. 비어 있으면 위기 아님. crisis를 주면 기본 crisis.json 대신 쓴다."""
    patterns = _default_patterns() if crisis is None else compile_patterns(crisis["keywords"], "crisis")
    return [CrisisHit(p.id, p.meta["category"]) for p in matched(masked_text, list(patterns))]
