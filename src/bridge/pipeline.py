"""질문 1건 처리 (CLAUDE.md 6장).

현재: 의도 분류(키워드 1차 + LLM 2차, PoC2-04)와 근거 제한 응답 생성(PoC2-07) 단계.
출력 검증·안전 응답·저장을 묶는 처리 함수는 PoC2-05·06·08·10 작업에서 추가한다.
"""
import json
from dataclasses import dataclass, field
from typing import Literal

from bridge import config, llm
from bridge.evidence import EvidencePack
from bridge.llm import LLMResult
from bridge.rules.intents import classify_by_keywords

INTENT_CODES = ("explain", "diagnosis", "parenting", "crisis", "out_of_scope")  # spec 2-5
QUESTION_TAG = "guardian_question"

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENT_CODES)},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "confidence"],
    "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "note_question": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["answerable", "answer", "evidence_ids", "note_question"],
    "additionalProperties": False,
}


def wrap_question(masked: str) -> str:
    """보호자 입력을 별도 태그 영역에 넣는다(G-08). 입력 속 꺾쇠는 전각으로 바꿔 태그를 만들 수 없게 한다."""
    body = masked.replace("<", "＜").replace(">", "＞")
    return f"<{QUESTION_TAG}>\n{body}\n</{QUESTION_TAG}>"


def _json_object(text: str | None) -> dict | None:
    try:
        value = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


# ── 의도 분류 (PoC2-04) ──────────────────────────────


@dataclass(frozen=True)
class IntentDecision:
    intent: str | None
    confidence: float | None
    source: Literal["keyword", "llm", "llm_invalid"]
    route: str
    keyword_hits: dict = field(default_factory=dict)
    llm: LLMResult | None = None


def _parse_intent(text: str | None) -> tuple[str, float] | None:
    """모델과 무관한 형식 검증(G-08): 의도 코드 안의 intent, 0~1 숫자 confidence."""
    value = _json_object(text)
    if value is None:
        return None
    intent, conf = value.get("intent"), value.get("confidence")
    if intent not in INTENT_CODES or isinstance(conf, bool) or not isinstance(conf, int | float):
        return None
    if not 0 <= conf <= 1:
        return None
    return intent, float(conf)


def classify_intent(masked: str, *, model: str | None = None, client=None) -> IntentDecision:
    """키워드로 정해지면 LLM을 부르지 않는다. LLM 결과가 깨졌거나 신뢰도 미달이면 safe.

    LLM이 crisis로 분류하면 신뢰도와 무관하게 crisis (spec PoC2-04, 안전 쪽 해석).
    입력은 마스킹된 질문만 보낸다(G-09). LLMError는 호출자가 처리한다(P-05).
    """
    kw = classify_by_keywords(masked)
    if kw.intent is not None:
        return IntentDecision(kw.intent, None, "keyword", config.ROUTE_BY_INTENT[kw.intent], kw.hits)

    version = config.PROMPT_VERSIONS["intent"]
    result = llm.call("intent", version, [llm.load_prompt(version)], wrap_question(masked), INTENT_SCHEMA,
                      model=model, client=client)
    parsed = _parse_intent(result.text)
    if parsed is None:
        return IntentDecision(None, None, "llm_invalid", config.UNCLASSIFIED_ROUTE, kw.hits, result)
    intent, conf = parsed
    route = config.ROUTE_BY_INTENT[intent]
    if intent != "crisis" and conf < config.INTENT_CONFIDENCE_THRESHOLD:
        route = config.UNCLASSIFIED_ROUTE
    return IntentDecision(intent, conf, "llm", route, kw.hits, result)


# ── 근거 제한 응답 생성 (PoC2-07) ────────────────────


@dataclass(frozen=True)
class AnswerDraft:
    parsed: dict | None        # JSON 객체가 아니면 None. 필드·근거·숫자 검증은 출력 검증(PoC2-08)
    llm: LLMResult


def generate_answer(masked: str, evidence: EvidencePack, *, model: str | None = None, client=None) -> AnswerDraft:
    """system = [정책, 근거 묶음(캐시 지점)], user = 태그로 감싼 마스킹 질문."""
    version = config.PROMPT_VERSIONS["answer"]
    system_parts = [llm.load_prompt(version), f"<evidence>\n{evidence.text}\n</evidence>"]
    result = llm.call("answer", version, system_parts, wrap_question(masked), ANSWER_SCHEMA,
                      model=model, client=client)
    return AnswerDraft(_json_object(result.text), result)
