"""content/ 로드·형식 검증과 사전 검사 대상 문장 추출 (content/README.md, PoC1-03·04·08).

문장은 미리 만들어 두고 코드가 조립만 한다(G-04). 숫자는 문장에 쓰지 않고 자리표시자로 둔다(G-03).
"""
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bridge import config
from bridge.rules.patterns import compile_patterns


class ContentError(ValueError):
    pass


CARD_RANGES = ("normal", "borderline", "clinical")
CARD_STATUSES = ("draft", "reviewed")
CARD_REQUIRED = ("id", "assessment", "scale", "range", "title", "what_it_asks", "behavior_examples",
                 "position_text", "report_recommendation", "status", "version", "reviewed_at")
CARD_SENTENCE_FIELDS = ("title", "what_it_asks", "behavior_examples", "position_text", "report_recommendation")

# 파일별 허용 자리표시자. 카드의 숫자는 view model(PoC1-02)에서만 채운다.
ALLOWED_PLACEHOLDERS = {
    "scale_cards.json": {"scale_name", "range_label"},
    "summary_templates.json": {"clinical_list", "borderline_list"},
    "glossary.json": set(),
}

# 파일별 문장 필드 = PoC1-08 검사 범위. 패턴 파일(guard_terms, intent_keywords)과 연락처는 넣지 않는다.
#   ("items", 필드들): 항목 배열, 각 항목의 필드 / ("values", None): 객체의 모든 값 / ("keys", 필드들): 객체의 해당 키
SENTENCE_FIELDS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "scale_cards.json": ("items", CARD_SENTENCE_FIELDS),
    "summary_templates.json": ("items", ("text",)),
    "glossary.json": ("items", ("term", "plain")),
    "safe_responses.json": ("items", ("text",)),
    "phrases.json": ("values", None),
    "crisis.json": ("keys", ("message",)),
}

# phrases.json 키별 허용 자리표시자. M1(PoC1-02·05·07) 키만 필수, 2일차 문구는 그때 추가한다.
PHRASE_PLACEHOLDERS = {
    "fixed_notice_results": set(),
    "percentile_known": {"rank_from_top"},
    "percentile_known_lower": {"percentile"},
    "direction_note_lower": set(),
    "percentile_unknown": set(),
    "not_administered": set(),
    "input_empty": set(),
    "input_too_long": {"max_chars"},
}
M1_PHRASE_KEYS = ("fixed_notice_results", "percentile_known", "percentile_known_lower",
                  "direction_note_lower", "percentile_unknown", "not_administered")
QA_PHRASE_KEYS = ("input_empty", "input_too_long")  # PoC-2 문구는 구현하면서 추가한다

CRISIS_REQUIRED = ("keywords", "message", "channels")
CRISIS_CATEGORIES = ("child_safety", "caregiver_distress")
# 위기는 crisis.json에 따로 둔다(위기 검사가 먼저 실행됨). diagnosis 우선 규칙은 bridge.rules.intents.
INTENT_KEYWORD_KEYS = ("diagnosis", "parenting", "out_of_scope", "explain")

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def load_json(name: str, content_dir: Path | None = None) -> Any:
    return json.loads(((content_dir or config.CONTENT_DIR) / name).read_text(encoding="utf-8"))


def _strings(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _check_placeholders(text: str, allowed: set[str], where: str) -> None:
    if extra := placeholders(text) - allowed:
        raise ContentError(f"{where}: 허용되지 않은 자리표시자 {sorted(extra)}")


def _check_unique(values: list, what: str) -> None:
    seen = set()
    for v in values:
        if v in seen:
            raise ContentError(f"중복 {what}: {v}")
        seen.add(v)


def card_sentences(card: dict) -> Iterator[str]:
    for field in CARD_SENTENCE_FIELDS:
        yield from _strings(card[field])


def load_scale_cards(content_dir: Path | None = None, definitions: dict[str, dict] | None = None) -> list[dict]:
    """definitions({검사 코드: 정의})를 주면 assessment·scale이 정의에 있는지도 확인한다."""
    cards = load_json("scale_cards.json", content_dir)
    allowed = ALLOWED_PLACEHOLDERS["scale_cards.json"]
    for c in cards:
        where = c.get("id", "?")
        if missing := [k for k in CARD_REQUIRED if k not in c]:
            raise ContentError(f"{where}: 필수 필드 누락 {missing}")
        if c["range"] not in CARD_RANGES:
            raise ContentError(f"{where}: 알 수 없는 range {c['range']!r}")
        if c["status"] not in CARD_STATUSES:
            raise ContentError(f"{where}: 알 수 없는 status {c['status']!r}")
        if definitions is not None:
            if c["assessment"] not in definitions:
                raise ContentError(f"{where}: 정의 없는 검사 {c['assessment']!r}")
            if "group" not in definitions[c["assessment"]]["scales"].get(c["scale"], {}):
                raise ContentError(f"{where}: 판정 기준(group) 없는 척도 {c['scale']!r}")
        for text in card_sentences(c):
            _check_placeholders(text, allowed, where)
    _check_unique([c["id"] for c in cards], "카드 id")
    _check_unique([(c["assessment"], c["scale"], c["range"]) for c in cards], "카드 (assessment, scale, range)")
    return cards


def load_summary_templates(content_dir: Path | None = None) -> list[dict]:
    """네 조건(has_clinical × has_borderline)이 빠짐없이, 겹치지 않게 있어야 한다.

    조건상 비어 있는 목록의 자리표시자(예: 임상이 없는데 {clinical_list})는 쓸 수 없다.
    """
    templates = load_json("summary_templates.json", content_dir)
    _check_unique([t["id"] for t in templates], "요약 템플릿 id")
    conditions = [(t["when"]["has_clinical"], t["when"]["has_borderline"]) for t in templates]
    _check_unique(conditions, "요약 조건")
    if set(conditions) != {(c, b) for c in (False, True) for b in (False, True)}:
        raise ContentError(f"요약 조건 누락: {sorted(conditions)}")
    for t in templates:
        allowed = set()
        if t["when"]["has_clinical"]:
            allowed.add("clinical_list")
        if t["when"]["has_borderline"]:
            allowed.add("borderline_list")
        _check_placeholders(t["text"], allowed, t["id"])
    return templates


def load_glossary(content_dir: Path | None = None) -> list[dict]:
    entries = load_json("glossary.json", content_dir)
    _check_unique([e["id"] for e in entries], "용어 id")
    _check_unique([w for e in entries for w in [e["term"], *e["aliases"]]], "용어·별칭")
    for e in entries:
        _check_placeholders(e["plain"], ALLOWED_PLACEHOLDERS["glossary.json"], e["id"])
    return entries


def load_phrases(content_dir: Path | None = None, required: tuple[str, ...] = M1_PHRASE_KEYS) -> dict[str, str]:
    phrases = load_json("phrases.json", content_dir)
    if missing := [k for k in required if k not in phrases]:
        raise ContentError(f"phrases.json: 필수 키 누락 {missing}")
    for key, text in phrases.items():
        _check_placeholders(text, PHRASE_PLACEHOLDERS.get(key, set()), f"phrases.{key}")
    return phrases


def _check_patterns(items: list[dict], where: str) -> None:
    try:
        compile_patterns(items, where)
    except (KeyError, ValueError) as e:
        raise ContentError(str(e)) from e


def load_crisis(content_dir: Path | None = None) -> dict:
    crisis = load_json("crisis.json", content_dir)
    if missing := [k for k in CRISIS_REQUIRED if k not in crisis]:
        raise ContentError(f"crisis.json: 필수 키 누락 {missing}")
    _check_unique([k["id"] for k in crisis["keywords"]], "위기 키워드 id")
    for k in crisis["keywords"]:
        if k.get("category") not in CRISIS_CATEGORIES:
            raise ContentError(f"{k['id']}: 알 수 없는 category {k.get('category')!r}")
    _check_patterns(crisis["keywords"], "crisis")
    return crisis


def load_intent_keywords(content_dir: Path | None = None) -> dict[str, list[dict]]:
    keywords = load_json("intent_keywords.json", content_dir)
    if set(keywords) != set(INTENT_KEYWORD_KEYS):
        raise ContentError(f"intent_keywords.json: 키는 정확히 {list(INTENT_KEYWORD_KEYS)} (현재 {sorted(keywords)})")
    _check_unique([k["id"] for items in keywords.values() for k in items], "의도 키워드 id")
    for intent, items in keywords.items():
        _check_patterns(items, f"intent.{intent}")
    return keywords


def iter_content_sentences(content_dir: Path | None = None) -> Iterator[tuple[str, str, str]]:
    """(파일명, 위치, 문장)을 돌려준다. 아직 없는 파일은 건너뛴다."""
    base = content_dir or config.CONTENT_DIR
    for name, (kind, fields) in SENTENCE_FIELDS.items():
        if not (base / name).exists():
            continue
        data = load_json(name, base)
        if kind == "items":
            for item in data:
                for field in fields:
                    for i, text in enumerate(_strings(item.get(field, []))):
                        yield name, f"{item['id']}.{field}[{i}]", text
        elif kind == "values":
            for key, value in data.items():
                for i, text in enumerate(_strings(value)):
                    yield name, f"{key}[{i}]", text
        else:
            for key in fields:
                for i, text in enumerate(_strings(data.get(key, []))):
                    yield name, f"{key}[{i}]", text
