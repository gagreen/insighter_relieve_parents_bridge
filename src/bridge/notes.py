"""질문 노트와 질문 정리 [PoC2-11, G-09, G-10].

저장 문장은 마스킹된 원래 질문이다(specs/poc.md PoC2-05). PoC에는 승인 흐름이 없고 parent_approved 컬럼만 둔다(G-10).
정리는 LLM 1회 + 모델과 무관한 검증. 실패하면 1회 재생성, 그래도 실패하면 노트 1건 = 항목 1개로 쓴다.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from bridge import config, llm
from bridge.guard.output import numbers_in
from bridge.guard.terms import GuardTerm, find_violations, load_guard_terms
from bridge.llm import LLMError, LLMResult

# 브리프 유형 (spec PoC2-11): 진단·치료·경과 / 양육 / 결과·용어 이해 / 기타
BRIEF_TYPES = ("diagnosis", "parenting", "understanding", "other")
# 정리 실패 시 노트 유형 → 브리프 유형
NOTE_TYPE_TO_BRIEF = {"diagnosis": "diagnosis", "parenting": "parenting",
                      "no_evidence": "understanding", "guard_fallback": "understanding"}
NOTES_TAG = "saved_questions"

ORGANIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": list(BRIEF_TYPES)},
                    "source_item_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "type", "source_item_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


def save_note(conn: sqlite3.Connection, child_id: str, turn_id: int, text: str, type_: str,
              related_refs: list[str]) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO note_items (child_id, source_turn_id, text, type, related_refs) VALUES (?, ?, ?, ?, ?)",
            (child_id, turn_id, text, type_, json.dumps(related_refs, ensure_ascii=False)),
        )
    return cur.lastrowid


def list_notes(conn: sqlite3.Connection, child_id: str, since_turn_id: int | None = None) -> list[dict]:
    """since_turn_id를 주면 그 턴 이후 노트만 (데모 세션 범위, spec 5장)."""
    rows = conn.execute(
        "SELECT * FROM note_items WHERE child_id = ? AND source_turn_id > ? ORDER BY item_id",
        (child_id, since_turn_id or 0),
    ).fetchall()
    return [{**dict(r), "related_refs": json.loads(r["related_refs"] or "[]")} for r in rows]


# ── 질문 정리 (PoC2-11) ──────────────────────────────


@dataclass(frozen=True)
class OrganizedItem:
    text: str
    type: str
    source_item_ids: list[int]
    source_turn_ids: list[int]     # 코드가 원래 노트에서 채움 (원래 질문과의 연결)
    related_refs: list[str]        # 코드가 원래 노트들의 related_refs를 합침


@dataclass(frozen=True)
class OrganizeResult:
    items: list[OrganizedItem]
    source: Literal["llm", "regen", "fallback", "skipped", "empty"]
    failures: list[list[str]] = field(default_factory=list)
    llm_calls: list[LLMResult] = field(default_factory=list)


def _item(text: str, type_: str, sources: list[dict]) -> OrganizedItem:
    refs = list(dict.fromkeys(r for n in sources for r in n["related_refs"]))
    return OrganizedItem(text, type_, [n["item_id"] for n in sources], [n["source_turn_id"] for n in sources], refs)


def fallback_items(notes: list[dict]) -> list[OrganizedItem]:
    """정리 없이 노트 1건 = 항목 1개. 유형은 노트 유형에서 규칙으로 옮긴다."""
    return [_item(n["text"], NOTE_TYPE_TO_BRIEF.get(n["type"], "other"), [n]) for n in notes]


def skipped(notes: list[dict]) -> OrganizeResult:
    """LLM 정리를 하지 않는 경우(CLI --no-llm)."""
    return OrganizeResult(fallback_items(notes), "skipped" if notes else "empty")


def _term_ids(text: str, terms: list[GuardTerm]) -> set[str]:
    return {v.term_id for v in find_violations(text, terms)}


def validate_organized(parsed: dict | None, notes: list[dict], terms: list[GuardTerm]) -> list[str]:
    """모델과 무관한 규칙(G-08): 형식 / 모든 노트가 정확히 한 번 / 원래 질문에 없던 금칙 표현·숫자가 생기지 않음."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        return ["format:json"]
    by_id = {n["item_id"]: n for n in notes}
    failures, seen = [], []
    for i, item in enumerate(parsed["items"]):
        ids = item.get("source_item_ids") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            failures.append(f"format:item[{i}].text")
            continue
        if item.get("type") not in BRIEF_TYPES:
            failures.append(f"format:item[{i}].type")
        if not isinstance(ids, list) or not ids or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
            failures.append(f"format:item[{i}].source_item_ids")
            continue
        failures += [f"unknown:{x}" for x in ids if x not in by_id]
        failures += [f"duplicate:{x}" for x in ids if x in seen]
        seen += ids
        sources = [by_id[x]["text"] for x in ids if x in by_id]
        failures += [f"term:{t}" for t in sorted(_term_ids(item["text"], terms) - set().union(*(_term_ids(s, terms) for s in sources)))]
        source_numbers = {n for s in sources for n in numbers_in(s)}
        failures += [f"number:{n}" for n in dict.fromkeys(numbers_in(item["text"])) if n not in source_numbers]
    failures += [f"missing:{x}" for x in by_id if x not in seen]
    return failures


def _notes_text(notes: list[dict]) -> str:
    lines = [json.dumps({"id": n["item_id"], "type": n["type"], "text": n["text"]}, ensure_ascii=False) for n in notes]
    return llm.tagged(NOTES_TAG, "\n".join(lines))


def organize_notes(conn: sqlite3.Connection, notes: list[dict], *, model: str | None = None, client=None,
                   terms: list[GuardTerm] | None = None) -> OrganizeResult:
    """노트가 0건이면 호출하지 않는다. 입력은 마스킹된 노트 문장과 id만(G-09). 호출은 turn_id 없이 기록한다."""
    if not notes:
        return OrganizeResult([], "empty")
    terms = terms if terms is not None else load_guard_terms()
    version = config.PROMPT_VERSIONS["organize"]
    by_id = {n["item_id"]: n for n in notes}
    calls, failures = [], []
    for attempt in range(1 + config.AUTO_REGEN_LIMIT):
        try:
            result = llm.call("organize", version, [llm.load_prompt(version)], _notes_text(notes), ORGANIZE_SCHEMA,
                              model=model, client=client)
        except LLMError:
            break
        llm.record_call(conn, None, result)
        calls.append(result)
        parsed = llm.parse_json_object(result.text)
        failures.append(validate_organized(parsed, notes, terms))
        if not failures[-1]:
            items = [_item(i["text"], i["type"], [by_id[x] for x in i["source_item_ids"]]) for i in parsed["items"]]
            return OrganizeResult(items, "llm" if attempt == 0 else "regen", failures, calls)
    return OrganizeResult(fallback_items(notes), "fallback", failures, calls)
