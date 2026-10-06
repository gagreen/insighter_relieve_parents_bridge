"""질문 1건 처리 (CLAUDE.md 6장).

입력 검증(P-01) → 마스킹(G-09) → 위기 키워드 → 의도 분류(키워드 1차 + LLM 2차) → 분기
  → [설명형만] 근거 제한 응답 생성 → 출력 검증(G-06, 실패 시 1회 재생성 후 안전 응답) → 저장.
LLM 생성은 설명형에만 쓴다. 위기·진단·양육·범위 밖·신뢰도 미달은 미리 만든 문장이다(G-04, G-05).
"""
import json
import logging
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from bridge import config, content, db, evidence, llm, notes, results
from bridge.evidence import EvidencePack
from bridge.guard.output import validate_answer
from bridge.guard.terms import GuardTerm, find_violations, load_guard_terms
from bridge.llm import LLMError, LLMResult
from bridge.rules.crisis import detect_crisis
from bridge.rules.input import check_input
from bridge.rules.glossary_match import annotate, term_ids
from bridge.rules.intents import classify_by_keywords, diagnosis_subroute
from bridge.rules.masking import mask_for_child

LABEL_AI = "AI 생성"        # G-11: AI 생성 응답 (근거 칩과 함께 표시)
LABEL_SAFE = "안전 응답"    # spec 5장: 미리 만든 문장 (위기·안전 응답·범위 밖·안내 문구)
LABEL_GLOSSARY = "낱말 풀이 · 초안(검수 전)"   # PoC2-14: 결과 화면 낱말 풀이와 같은 표시 (G-11)
LABEL_GUIDE = "안내 · 초안(검수 전)"           # PoC2-15: 상담 준비 안내 (G-11)
alert_log = logging.getLogger("bridge.alert")   # PoC2-03 알림 로그

INTENT_CODES = ("explain", "diagnosis", "parenting", "crisis", "out_of_scope", "consult_prep")  # spec 2-5
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
    safe_kind: str | None = None     # route = safe일 때 정해진 안전 응답 종류 (진단명 뜻, PoC2-04 예외 2)


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


def classify_intent(masked: str, *, model: str | None = None, client=None,
                    prompts: Mapping[str, str] | None = None) -> IntentDecision:
    """키워드로 정해지면 LLM을 부르지 않는다. LLM 결과가 깨졌거나 신뢰도 미달이면 safe.

    LLM이 crisis로 분류하면 신뢰도와 무관하게 crisis (spec PoC2-04, 안전 쪽 해석).
    입력은 마스킹된 질문만 보낸다(G-09). LLMError는 호출자가 처리한다(P-05).
    prompts는 단계 → 프롬프트 버전(평가의 --prompt-set, spec 6-1). 없으면 config.PROMPT_VERSIONS.
    """
    kw = classify_by_keywords(masked)
    if kw.intent == "diagnosis":
        # 진단 우선의 예외: 낱말 뜻 → glossary, 진단명 뜻 → diagnosis_term (spec PoC2-04, 2026-10-06)
        sub = diagnosis_subroute(masked)
        if sub == "glossary":
            return IntentDecision(kw.intent, None, "keyword", "glossary", kw.hits)
        if sub == "diagnosis_term":
            return IntentDecision(kw.intent, None, "keyword", "safe", kw.hits, safe_kind="diagnosis_term")
    if kw.intent is not None:
        return IntentDecision(kw.intent, None, "keyword", config.ROUTE_BY_INTENT[kw.intent], kw.hits)

    version = (prompts or config.PROMPT_VERSIONS)["intent"]
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


RETRY_TAG = "retry_feedback"
_TRUSTED_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")     # 모델이 만든 id는 이 형식일 때만 사유에 옮긴다 (G-08)


def _retry_line(code: str) -> str:
    kind, _, arg = code.partition(":")
    if kind == "number":
        return (f"숫자 {arg}은(는) 인용한 근거 항목에 없습니다. 근거에 있는 숫자만 쓰고, 그 숫자가 있는 항목의 id를 "
                "evidence_ids에 넣습니다. 예시를 위한 숫자나 직접 계산한 숫자는 쓰지 않습니다.")
    if code == "evidence:empty":
        return ("답을 썼으면 evidence_ids에 사용한 근거 항목의 id를 하나 이상 넣습니다. "
                "근거로 답할 사실이 전혀 없으면 answer를 빈 문자열로 둡니다.")
    if kind == "evidence":
        bad_id = arg.removeprefix("unknown:")
        named = f"id '{bad_id}'" if _TRUSTED_ID.fullmatch(bad_id) else "근거에 없는 id"
        return f"{named}는 근거에 없습니다. id는 근거 줄의 id를 글자 그대로 복사합니다."
    if kind == "term":
        return "진단 가능성·예후·안심 판단처럼 쓰지 않기로 한 표현이 들어 있습니다. 그 표현을 빼고 다시 씁니다."
    if kind == "range_label":
        return f"범위 이름 '{arg}'은(는) 인용한 점수 항목의 범위가 아닙니다. 근거의 range_label만 씁니다."
    if kind == "format":
        return "출력 형식이 맞지 않습니다. 지정한 JSON 필드를 모두 채웁니다."
    return "출력 검증에 실패했습니다. 규칙을 다시 확인해 씁니다."


def retry_feedback(failures: list[str]) -> list[str]:
    """출력 검증 실패 사유 코드 → 재생성 요청에 붙일 문장 (spec PoC2-08, 2026-10-06). 같은 문장은 한 번만.

    금칙 사전 id는 알리지 않는다. 모델이 만든 id는 형식에 맞을 때만 옮긴다(G-08).
    """
    return list(dict.fromkeys(_retry_line(code) for code in failures))


def generate_answer(masked: str, evidence: EvidencePack, *, model: str | None = None, client=None,
                    prompts: Mapping[str, str] | None = None, feedback: list[str] | None = None) -> AnswerDraft:
    """system = [정책, 근거 묶음(캐시 지점)], user = 태그로 감싼 마스킹 질문 (+ 재생성이면 질문 태그 밖에 실패 사유)."""
    version = (prompts or config.PROMPT_VERSIONS)["answer"]
    system_parts = [llm.load_prompt(version), f"<evidence>\n{evidence.text}\n</evidence>"]
    user_text = wrap_question(masked)
    if feedback:
        user_text += "\n\n" + llm.tagged(RETRY_TAG, "\n".join(f"- {line}" for line in feedback))
    result = llm.call("answer", version, system_parts, user_text, ANSWER_SCHEMA, model=model, client=client)
    return AnswerDraft(llm.parse_json_object(result.text), result)


def drop_unsupported_text(parsed: dict | None) -> dict | None:
    """answerable=false인데 근거가 비어 있으면 답 문장을 버린다 → '보고서에 없음' 안내 경로 (spec PoC2-07, G-07).

    마지막 시도에만 쓴다. 버린 문장은 화면에 나가지 않는다(2026-10-06).
    """
    if isinstance(parsed, dict) and parsed.get("answerable") is False and parsed.get("evidence_ids") == []:
        return {**parsed, "answer": ""}
    return parsed


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
    glossary: list[dict]       # 낱말 풀이(PoC1-10)·근거 묶음


def load_context(conn: sqlite3.Connection, result_id: str) -> Context:
    result = db.get_result(conn, result_id)
    payload = result["payload"]
    definition = db.get_definition(conn, result["assessment_code"])
    phrases = content.load_phrases(required=content.M1_PHRASE_KEYS + content.QA_PHRASE_KEYS)
    glossary = content.load_glossary()
    view = results.build_view(payload, definition, content.load_scale_cards(),
                              content.load_summary_templates(), phrases, glossary)
    return Context(
        result_id=result_id, child_id=result["child_id"], payload=payload, definition=definition, view=view,
        pack=evidence.build_evidence(view, payload, glossary),
        phrases=phrases, safe_responses=content.load_safe_responses(),
        scale_terms=[t for t in content.load_scale_terms() if t["assessment"] == payload["assessment"]],
        terms=load_guard_terms(), crisis=content.load_crisis(), glossary=glossary,
    )


# ── 안전 응답 (PoC2-05) ──────────────────────────────


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def find_scales(masked: str, ctx: Context) -> list[dict]:
    """질문에 나온 척도(view 항목). 척도 이름 일치가 먼저, 그다음 scale_terms 표현. 그 안에서는 payload 순서.

    이름이 일치한 부분은 표현 검색에서 뺀다('정서불안정'의 '불안'으로 우울/불안을 다시 찾지 않음).
    """
    question = _compact(masked)
    items = ctx.view["items"]
    by_name = [i for i in items if _compact(i["name"]) in question]
    rest = question
    for i in by_name:
        rest = rest.replace(_compact(i["name"]), " ")
    terms = {t["scale"]: t["terms"] for t in ctx.scale_terms}
    by_term = [i for i in items if i not in by_name
               and any(_compact(w) in rest for w in terms.get(i["scale"], []))]
    return by_name + by_term


def _report_quote(scale: str, ctx: Context) -> tuple[str, str] | None:
    """(서술 id, 첫 줄). 척도에 연결된 관찰 소견의 첫 줄(관찰 사실). 금칙 표현에 걸리면 인용하지 않는다(B-4)."""
    finding = next((f for f in ctx.payload["findings"] if f["type"] == "observation" and f["scale"] == scale), None)
    if finding is None:
        return None
    line = finding["text"].split("\n")[0].strip()
    if not line or find_violations(line, ctx.terms):
        return None
    return finding["id"], line


def with_note_saved(text: str, ctx: Context) -> str:
    """노트에 저장한 응답 끝에 다음 단계 안내를 붙인다 (spec 1-1 R-2)."""
    return f"{text} {ctx.phrases['note_saved']}"


def safe_response(kind: str, masked: str, ctx: Context) -> tuple[str, list[str]]:
    """(문장, 근거 id). 공감 → 척도 사실 → 보고서 인용 → 본문 → 선별 검사 안내 → note_saved → 준비 행동 (PoC2-05).

    미리 만든 문장만 조립한다(G-04). 숫자·인용은 view·payload에서만 채운다(G-03). LLM을 호출하지 않는다(G-05).
    """
    template = next(t for t in ctx.safe_responses if t["kind"] == kind)
    found = find_scales(masked, ctx)
    if kind == "diagnosis_term":
        return _diagnosis_term_response(template, found, ctx)
    refs = [i["id"] for i in found]
    stated = [i for i in found if i["t"] is not None and i["range_label"]][:config.SAFE_MAX_SCALES]

    parts = [template["empathy"]]
    parts += [ctx.phrases["safe_scale_fact"].format(scale_name=i["name"], t=i["t"], range_label=i["range_label"])
              for i in stated]
    if stated and (quote := _report_quote(stated[0]["scale"], ctx)):
        refs.append(quote[0])
        parts.append(ctx.phrases["safe_report_quote"].format(quote=quote[1]))
    parts.append(template["body"])
    if template["screening_note"]:
        parts.append(ctx.phrases["screening_note"])
    parts += [ctx.phrases["note_saved"], template["closing"]]
    return " ".join(p for p in parts if p), refs


def _diagnosis_term_response(template: dict, found: list[dict], ctx: Context) -> tuple[str, list[str]]:
    """진단명 뜻 (PoC2-05 diagnosis_term): 본문 → 관련 척도 + 묻는 행동 → 척도 사실 → 선별 검사 → note_saved → 준비 행동.

    진단명은 다시 쓰지 않는다(G-01). 관련 척도는 질문에서 찾은 첫 척도 1개.
    """
    parts = [template["body"]]
    top = found[0] if found else None
    if top:
        parts.append(ctx.phrases["diagnosis_term_scale"].format(scale_name=top["name"]))
        if top["explanation"]["kind"] == "card":
            parts.append(top["explanation"]["card"]["what_it_asks"])
        if top["t"] is not None and top["range_label"]:
            parts.append(ctx.phrases["safe_scale_fact"].format(scale_name=top["name"], t=top["t"],
                                                               range_label=top["range_label"]))
    if template["screening_note"]:
        parts.append(ctx.phrases["screening_note"])
    parts += [ctx.phrases["note_saved"], template["closing"]]
    return " ".join(p for p in parts if p), [top["id"]] if top else []


# ── 낱말 뜻 (PoC2-14), 상담 준비 안내 (PoC2-15) ──────


def glossary_response(masked: str, ctx: Context) -> tuple[str, list[str], bool]:
    """(문장, 용어 id, 해석 표현 여부). 결과 화면 낱말 풀이와 같은 용어사전 문장으로만 답한다(G-04, LLM 없음).

    표현이 금칙 표현에 걸리면 다시 쓰지 않고 풀이만 쓰며, 이때는 용어 1개만 답한다(B-4).
    """
    by_id = {g["id"]: g for g in ctx.glossary}
    ids = list(dict.fromkeys(term_ids(annotate(masked, ctx.glossary))))[:config.GLOSSARY_QA_MAX_TERMS]
    entries = [by_id[i] for i in ids]
    unsafe = {e["id"] for e in entries if find_violations(e["term"], ctx.terms)}
    if unsafe:
        entries = entries[:1]
    parts = [ctx.phrases["glossary_answer_unnamed"].format(plain=e["plain"]) if e["id"] in unsafe
             else ctx.phrases["glossary_answer"].format(term=e["term"], plain=e["plain"]) for e in entries]
    interpretive = any(e["kind"] == "interpretive" for e in entries)
    if interpretive:
        parts.append(ctx.phrases["interpretive_note"])
    return " ".join(parts), [e["id"] for e in entries], interpretive


def prep_response(ctx: Context, saved: list[dict]) -> str:
    """상담 준비 안내: 도입 → 한 줄 요약(PoC1-03) → 관찰 메모 → 저장된 질문 목록 → 상담사 확인 안내 (LLM 없음)."""
    head = " ".join([ctx.phrases["prep_intro"], ctx.view["summary"]["text"], ctx.phrases["prep_memo"]])
    if saved:
        listing = "\n".join([ctx.phrases["prep_notes_intro"], *(f"- {n['text']}" for n in saved)])
    else:
        listing = ctx.phrases["prep_no_notes"]
    return "\n\n".join([head, listing, ctx.phrases["prep_closing"]])


def crisis_message(crisis: dict) -> str:
    lines = [crisis["message"]] + [f"- {c['name']}: {c['contact']}" for c in crisis["channels"]]
    return "\n".join(lines)


# ── 질문 1건 처리 ────────────────────────────────────


@dataclass(frozen=True)
class TurnResult:
    route: str                                   # input_error | crisis | safe | redirect | answer | api_error
                                                 # | glossary | prep (2026-10-06)
    message: str
    label: str | None = None                     # LABEL_AI / LABEL_SAFE (G-11)
    evidence_ids: list[str] = field(default_factory=list)
    guard_result: str | None = None              # pass | regen | fallback (설명형만)
    guard_failures: list[list[str]] = field(default_factory=list)   # 시도별 출력 검증 실패 사유
    crisis: bool = False
    stopped: bool = False                        # 위기 → 대화 중단 (입력 막기는 화면이 한다)
    note_saved: bool = False
    intent: str | None = None
    question_masked: str | None = None           # 외부로 보낸 문장 (화면에 'AI에게 보낸 문장'으로 표시, G-09)
    turn_id: int | None = None                   # input_error면 저장하지 않아 None
    llm_calls: list[LLMResult] = field(default_factory=list)
    safe_kind: str | None = None                 # 안전 응답 종류 (PoC2-05), 평가 채점용


@dataclass
class _Turn:
    masked: str
    intent: str | None = None
    confidence: float | None = None
    calls: list[LLMResult] = field(default_factory=list)
    failures: list[list[str]] = field(default_factory=list)


def _save(conn: sqlite3.Connection, ctx: Context, turn: _Turn, *, route: str, message: str, label: str,
          evidence_ids: list[str] = (), guard: str | None = None, crisis: bool = False,
          note: tuple[str, list[str]] | None = None, safe_kind: str | None = None) -> TurnResult:
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
                      intent=turn.intent, question_masked=turn.masked, turn_id=turn_id, llm_calls=list(turn.calls),
                      safe_kind=safe_kind)


def _crisis(conn, ctx: Context, turn: _Turn, stage: str, keyword_ids: list[str]) -> TurnResult:
    """대화 중단 + 위기 안내 + 알림 로그. 노트에는 저장하지 않고 crisis_flag로 브리프에 전달한다(G-05, G-10)."""
    turn.intent = "crisis"
    result = _save(conn, ctx, turn, route="crisis", message=crisis_message(ctx.crisis), label=LABEL_SAFE, crisis=True)
    alert_log.warning("crisis turn_id=%s child_id=%s stage=%s keywords=%s",
                      result.turn_id, ctx.child_id, stage, ",".join(keyword_ids) or "-")
    return result


def _safe(conn, ctx: Context, turn: _Turn, kind: str) -> TurnResult:
    text, refs = safe_response(kind, turn.masked, ctx)
    return _save(conn, ctx, turn, route="safe", message=text, label=LABEL_SAFE, evidence_ids=refs, note=(kind, refs),
                 safe_kind=kind)


def _glossary(conn, ctx: Context, turn: _Turn) -> TurnResult:
    """낱말 뜻 (PoC2-14). 해석 표현이면 상담 안내 + 노트 저장(결과 화면의 상담 질문 저장과 같은 유형)."""
    text, ids, interpretive = glossary_response(turn.masked, ctx)
    if interpretive:
        return _save(conn, ctx, turn, route="glossary", message=with_note_saved(text, ctx), label=LABEL_GLOSSARY,
                     evidence_ids=ids, note=(notes.REPORT_PHRASE_TYPE, ids))
    return _save(conn, ctx, turn, route="glossary", message=text, label=LABEL_GLOSSARY, evidence_ids=ids)


def _prep(conn, ctx: Context, turn: _Turn, since_turn_id: int | None) -> TurnResult:
    """상담 준비 안내 (PoC2-15). 노트에 저장하지 않는다."""
    saved = notes.list_notes(conn, ctx.child_id, since_turn_id)
    return _save(conn, ctx, turn, route="prep", message=prep_response(ctx, saved), label=LABEL_GUIDE)


def _api_error(conn, ctx: Context, turn: _Turn) -> TurnResult:
    """P-05: SDK 재시도 후에도 실패. 성공한 호출만 기록하고 질문은 노트에 저장한다(PoC2-10)."""
    return _save(conn, ctx, turn, route="api_error", message=with_note_saved(ctx.phrases["api_error"], ctx),
                 label=LABEL_SAFE, note=("api_error", []))


def _validate(parsed: dict | None, ctx: Context):
    return validate_answer(parsed, ctx.pack, ctx.terms, ctx.definition["range_labels"])


def _answer(conn, ctx: Context, turn: _Turn, model: str | None, client, prompts) -> TurnResult:
    """생성 → 검증. 실패하면 사유를 붙여 AUTO_REGEN_LIMIT회 재생성, 그래도 실패하면 guard_fallback 안전 응답(G-06)."""
    feedback = None
    for attempt in range(1 + config.AUTO_REGEN_LIMIT):
        try:
            draft = generate_answer(turn.masked, ctx.pack, model=model, client=client, prompts=prompts,
                                    feedback=feedback)
        except LLMError:
            return _api_error(conn, ctx, turn)
        turn.calls.append(draft.llm)
        parsed = draft.parsed
        report = _validate(parsed, ctx)
        turn.failures.append(report.failures)
        if not report.ok and attempt == config.AUTO_REGEN_LIMIT:
            # 마지막 시도가 근거 없이 쓴 문장 때문에만 실패했으면 fallback 대신 '보고서에 없음' (spec PoC2-07)
            dropped = drop_unsupported_text(parsed)
            if dropped is not parsed and (dropped_report := _validate(dropped, ctx)).ok:
                parsed, report = dropped, dropped_report
        if not report.ok:
            feedback = retry_feedback(report.failures)
            continue
        guard = "pass" if attempt == 0 else "regen"
        answer, ids = parsed["answer"], parsed["evidence_ids"]
        if parsed["answerable"]:
            return _save(conn, ctx, turn, route="answer", message=answer, label=LABEL_AI, evidence_ids=ids, guard=guard)
        if answer.strip():
            # 부분 답변: 근거에 있는 부분만 답하고 질문은 노트로 (PoC2-07, G-07)
            return _save(conn, ctx, turn, route="answer", message=with_note_saved(answer, ctx), label=LABEL_AI,
                         evidence_ids=ids, guard=guard, note=("no_evidence", ids))
        # G-07: 근거로 답할 수 없음 → 안내 + 노트
        return _save(conn, ctx, turn, route="answer", message=with_note_saved(ctx.phrases["no_evidence"], ctx),
                     label=LABEL_SAFE, guard=guard, note=("no_evidence", []))
    text, refs = safe_response("guard_fallback", turn.masked, ctx)
    return _save(conn, ctx, turn, route="answer", message=text, label=LABEL_SAFE, evidence_ids=refs,
                 guard="fallback", note=("guard_fallback", refs), safe_kind="guard_fallback")


def _is_low_confidence(decision: IntentDecision) -> bool:
    return decision.source == "llm_invalid" or (
        decision.source == "llm" and decision.confidence < config.INTENT_CONFIDENCE_THRESHOLD)


def handle_question(conn: sqlite3.Connection, ctx: Context, raw: str, *, model: str | None = None,
                    client=None, prompts: Mapping[str, str] | None = None,
                    since_turn_id: int | None = None) -> TurnResult:
    """보호자 질문 1건. 입력 검증 실패는 저장하지 않는다. 그 밖에는 qa_turns 1행을 남긴다.

    since_turn_id: 상담 준비 안내(PoC2-15)에 나열할 노트의 범위(화면 세션, spec 5장). 없으면 전체.
    """
    check = check_input(raw, ctx.phrases)
    if not check.ok:
        return TurnResult(route="input_error", message=check.message)

    turn = _Turn(mask_for_child(conn, ctx.child_id, raw).text)
    if hits := detect_crisis(turn.masked):
        return _crisis(conn, ctx, turn, "keyword", [h.keyword_id for h in hits])

    try:
        decision = classify_intent(turn.masked, model=model, client=client, prompts=prompts)
    except LLMError:
        return _api_error(conn, ctx, turn)
    turn.intent, turn.confidence = decision.intent, decision.confidence
    if decision.llm is not None:
        turn.calls.append(decision.llm)

    if decision.route == "crisis":
        return _crisis(conn, ctx, turn, "intent_llm", [])
    if decision.route == "redirect":
        return _save(conn, ctx, turn, route="redirect", message=ctx.phrases["out_of_scope"], label=LABEL_SAFE)
    if decision.route == "glossary":
        return _glossary(conn, ctx, turn)
    if decision.route == "prep":
        return _prep(conn, ctx, turn, since_turn_id)
    if decision.route == "safe":
        if decision.safe_kind:
            return _safe(conn, ctx, turn, decision.safe_kind)
        low = _is_low_confidence(decision) or decision.intent not in ("diagnosis", "parenting")
        return _safe(conn, ctx, turn, "low_confidence" if low else decision.intent)
    return _answer(conn, ctx, turn, model, client, prompts)
