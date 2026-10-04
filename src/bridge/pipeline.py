"""질문 1건 처리 (CLAUDE.md 6장).

입력 검증(P-01) → 마스킹(G-09) → 위기 키워드 → 의도 분류(키워드 1차 + LLM 2차) → 분기
  → [설명형만] 근거 제한 응답 생성 → 출력 검증(G-06, 실패 시 1회 재생성 후 안전 응답) → 저장.
LLM 생성은 설명형에만 쓴다. 위기·진단·양육·범위 밖·신뢰도 미달은 미리 만든 문장이다(G-04, G-05).
"""
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from bridge import config, content, db, evidence, llm, notes, results
from bridge.evidence import EvidencePack
from bridge.guard.output import validate_answer
from bridge.guard.terms import GuardTerm, load_guard_terms
from bridge.llm import LLMError, LLMResult
from bridge.rules.crisis import detect_crisis
from bridge.rules.input import check_input
from bridge.rules.intents import classify_by_keywords
from bridge.rules.masking import mask_for_child

LABEL_AI = "AI 생성"        # G-11: AI 생성 응답 (근거 칩과 함께 표시)
LABEL_SAFE = "안전 응답"    # spec 5장: 미리 만든 문장 (위기·안전 응답·범위 밖·안내 문구)
alert_log = logging.getLogger("bridge.alert")   # PoC2-03 알림 로그

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
    """보호자 질문을 별도 태그 영역에 넣는다(G-08)."""
    return llm.tagged(QUESTION_TAG, masked)


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
    value = llm.parse_json_object(text)
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
    return AnswerDraft(llm.parse_json_object(result.text), result)


# ── 맥락 (아동 1명당 한 번) ──────────────────────────


@dataclass(frozen=True)
class Context:
    """검사 결과 1건에 대한 처리 맥락. 식별 정보(subjects)는 담지 않는다(G-09)."""
    result_id: str
    child_id: str
    payload: dict
    definition: dict
    view: dict
    pack: EvidencePack
    phrases: dict[str, str]
    safe_responses: list[dict]
    scale_terms: list[dict]    # 이 검사의 항목만
    terms: list[GuardTerm]
    crisis: dict


def load_context(conn: sqlite3.Connection, result_id: str) -> Context:
    result = db.get_result(conn, result_id)
    payload = result["payload"]
    definition = db.get_definition(conn, result["assessment_code"])
    phrases = content.load_phrases(required=content.M1_PHRASE_KEYS + content.QA_PHRASE_KEYS)
    view = results.build_view(payload, definition, content.load_scale_cards(),
                              content.load_summary_templates(), phrases)
    return Context(
        result_id=result_id, child_id=result["child_id"], payload=payload, definition=definition, view=view,
        pack=evidence.build_evidence(view, payload, content.load_glossary()),
        phrases=phrases, safe_responses=content.load_safe_responses(),
        scale_terms=[t for t in content.load_scale_terms() if t["assessment"] == payload["assessment"]],
        terms=load_guard_terms(), crisis=content.load_crisis(),
    )


# ── 안전 응답 (PoC2-05) ──────────────────────────────


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def find_scales(masked: str, ctx: Context) -> list[dict]:
    """질문에 나온 척도(view 항목). 척도 이름 일치가 먼저, 그다음 scale_terms 표현. 그 안에서는 payload 순서."""
    question = _compact(masked)
    items = ctx.view["items"]
    by_name = [i for i in items if _compact(i["name"]) in question]
    terms = {t["scale"]: t["terms"] for t in ctx.scale_terms}
    by_term = [i for i in items if i not in by_name
               and any(_compact(w) in question for w in terms.get(i["scale"], []))]
    return by_name + by_term


def safe_response(kind: str, masked: str, ctx: Context) -> tuple[str, list[str]]:
    """(문장, 관련 척도 id). 첫 척도에 T점수와 범위 이름(규칙 판정)이 있으면 척도 템플릿, 아니면 일반 템플릿.

    숫자는 view(= payload)에서만 채운다(G-03). LLM을 호출하지 않는다(G-05).
    """
    templates = [t for t in ctx.safe_responses if kind in t["intents"]]
    found = find_scales(masked, ctx)
    refs = [i["id"] for i in found]
    top = found[0] if found else None
    scale_template = next((t for t in templates if t["requires_scale"]), None)
    if top and top["t"] is not None and top["range_label"] and scale_template:
        return scale_template["text"].format(scale_name=top["name"], t=top["t"], range_label=top["range_label"]), refs
    return next(t for t in templates if not t["requires_scale"])["text"], refs


def crisis_message(crisis: dict) -> str:
    lines = [crisis["message"]] + [f"- {c['name']}: {c['contact']}" for c in crisis["channels"]]
    return "\n".join(lines)


# ── 질문 1건 처리 ────────────────────────────────────


@dataclass(frozen=True)
class TurnResult:
    route: str                                   # input_error | crisis | safe | redirect | answer | api_error
    message: str
    label: str | None = None                     # LABEL_AI / LABEL_SAFE (G-11)
    evidence_ids: list[str] = field(default_factory=list)
    guard_result: str | None = None              # pass | regen | fallback (설명형만)
    guard_failures: list[list[str]] = field(default_factory=list)   # 시도별 출력 검증 실패 사유
    crisis: bool = False
    stopped: bool = False                        # 위기 → 대화 중단 (입력 막기는 화면이 한다)
    note_saved: bool = False
    intent: str | None = None
    turn_id: int | None = None                   # input_error면 저장하지 않아 None
    llm_calls: list[LLMResult] = field(default_factory=list)


@dataclass
class _Turn:
    masked: str
    intent: str | None = None
    confidence: float | None = None
    calls: list[LLMResult] = field(default_factory=list)
    failures: list[list[str]] = field(default_factory=list)


def _save(conn: sqlite3.Connection, ctx: Context, turn: _Turn, *, route: str, message: str, label: str,
          evidence_ids: list[str] = (), guard: str | None = None, crisis: bool = False,
          note: tuple[str, list[str]] | None = None) -> TurnResult:
    """qa_turns 1행 → 이 턴의 llm_calls → note_items (PoC2-13). 노트 문장은 마스킹된 원래 질문."""
    with conn:
        cur = conn.execute(
            "INSERT INTO qa_turns (child_id, question_masked, intent, intent_confidence, route, answer,"
            " evidence_refs, guard_result, crisis_flag, saved_to_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ctx.child_id, turn.masked, turn.intent, turn.confidence, route, message,
             json.dumps(list(evidence_ids), ensure_ascii=False), guard, int(crisis), int(note is not None)),
        )
    turn_id = cur.lastrowid
    for call in turn.calls:
        llm.record_call(conn, turn_id, call)
    if note is not None:
        notes.save_note(conn, ctx.child_id, turn_id, turn.masked, note[0], note[1])
    return TurnResult(route=route, message=message, label=label, evidence_ids=list(evidence_ids), guard_result=guard,
                      guard_failures=turn.failures, crisis=crisis, stopped=crisis, note_saved=note is not None,
                      intent=turn.intent, turn_id=turn_id, llm_calls=list(turn.calls))


def _crisis(conn, ctx: Context, turn: _Turn, stage: str, keyword_ids: list[str]) -> TurnResult:
    """대화 중단 + 위기 안내 + 알림 로그. 노트에는 저장하지 않고 crisis_flag로 브리프에 전달한다(G-05, G-10)."""
    turn.intent = "crisis"
    result = _save(conn, ctx, turn, route="crisis", message=crisis_message(ctx.crisis), label=LABEL_SAFE, crisis=True)
    alert_log.warning("crisis turn_id=%s child_id=%s stage=%s keywords=%s",
                      result.turn_id, ctx.child_id, stage, ",".join(keyword_ids) or "-")
    return result


def _safe(conn, ctx: Context, turn: _Turn, kind: str) -> TurnResult:
    text, refs = safe_response(kind, turn.masked, ctx)
    return _save(conn, ctx, turn, route="safe", message=text, label=LABEL_SAFE, evidence_ids=refs, note=(kind, refs))


def _api_error(conn, ctx: Context, turn: _Turn) -> TurnResult:
    """P-05: SDK 재시도 후에도 실패. 성공한 호출만 기록하고 질문은 노트에 저장한다(PoC2-10)."""
    return _save(conn, ctx, turn, route="api_error", message=ctx.phrases["api_error"], label=LABEL_SAFE,
                 note=("api_error", []))


def _answer(conn, ctx: Context, turn: _Turn, model: str | None, client) -> TurnResult:
    """생성 → 검증. 실패하면 AUTO_REGEN_LIMIT회 재생성, 그래도 실패하면 guard_fallback 안전 응답(G-06)."""
    for attempt in range(1 + config.AUTO_REGEN_LIMIT):
        try:
            draft = generate_answer(turn.masked, ctx.pack, model=model, client=client)
        except LLMError:
            return _api_error(conn, ctx, turn)
        turn.calls.append(draft.llm)
        report = validate_answer(draft.parsed, ctx.pack, ctx.terms, ctx.definition["range_labels"])
        turn.failures.append(report.failures)
        if not report.ok:
            continue
        guard = "pass" if attempt == 0 else "regen"
        if draft.parsed["answerable"]:
            return _save(conn, ctx, turn, route="answer", message=draft.parsed["answer"], label=LABEL_AI,
                         evidence_ids=draft.parsed["evidence_ids"], guard=guard)
        # G-07: 근거로 답할 수 없음 → 안내 + 노트
        return _save(conn, ctx, turn, route="answer", message=ctx.phrases["no_evidence"], label=LABEL_SAFE,
                     guard=guard, note=("no_evidence", []))
    text, refs = safe_response("guard_fallback", turn.masked, ctx)
    return _save(conn, ctx, turn, route="answer", message=text, label=LABEL_SAFE, evidence_ids=refs,
                 guard="fallback", note=("guard_fallback", refs))


def _is_low_confidence(decision: IntentDecision) -> bool:
    return decision.source == "llm_invalid" or (
        decision.source == "llm" and decision.confidence < config.INTENT_CONFIDENCE_THRESHOLD)


def handle_question(conn: sqlite3.Connection, ctx: Context, raw: str, *, model: str | None = None,
                    client=None) -> TurnResult:
    """보호자 질문 1건. 입력 검증 실패는 저장하지 않는다. 그 밖에는 qa_turns 1행을 남긴다."""
    check = check_input(raw, ctx.phrases)
    if not check.ok:
        return TurnResult(route="input_error", message=check.message)

    turn = _Turn(mask_for_child(conn, ctx.child_id, raw).text)
    if hits := detect_crisis(turn.masked):
        return _crisis(conn, ctx, turn, "keyword", [h.keyword_id for h in hits])

    try:
        decision = classify_intent(turn.masked, model=model, client=client)
    except LLMError:
        return _api_error(conn, ctx, turn)
    turn.intent, turn.confidence = decision.intent, decision.confidence
    if decision.llm is not None:
        turn.calls.append(decision.llm)

    if decision.route == "crisis":
        return _crisis(conn, ctx, turn, "intent_llm", [])
    if decision.route == "redirect":
        return _save(conn, ctx, turn, route="redirect", message=ctx.phrases["out_of_scope"], label=LABEL_SAFE)
    if decision.route == "safe":
        low = _is_low_confidence(decision) or decision.intent not in ("diagnosis", "parenting")
        return _safe(conn, ctx, turn, "low_confidence" if low else decision.intent)
    return _answer(conn, ctx, turn, model, client)
