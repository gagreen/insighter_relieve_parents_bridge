"""PoC1-08 콘텐츠 사전 검사 → B-3, 콘텐츠 형식 검증 (content/README.md)."""
import json
import re
import shutil

import pytest

from bridge import config, content
from bridge.content import ContentError
from bridge.guard.terms import find_violations, load_guard_terms

RANGES = ("normal", "borderline", "clinical")


@pytest.fixture(scope="module")
def definitions():
    out = {}
    for path in config.ASSESSMENT_TYPES_DIR.glob("*.json"):
        t = json.loads(path.read_text(encoding="utf-8"))
        out[t["code"]] = t["definition"]
    return out


@pytest.fixture
def content_copy(tmp_path):
    """실제 content/를 복사한 임시 디렉터리 (잘못된 콘텐츠 주입용)."""
    dst = tmp_path / "content"
    shutil.copytree(config.CONTENT_DIR, dst)
    return dst


def _edit(dir_, name, fn):
    path = dir_ / name
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(fn(data), ensure_ascii=False), encoding="utf-8")


# ── PoC1-08 사전 검사 ─────────────────────────────────


def test_poc1_08_sentence_scan_is_not_empty():
    """검사 대상이 0건이라 통과하는 일을 막는다."""
    files = {f for f, _, _ in content.iter_content_sentences()}
    assert {"scale_cards.json", "summary_templates.json", "glossary.json"} <= files


def test_poc1_08_content_sentences_have_no_guard_violations():
    """PoC1-08 / B-3: content/의 모든 문장이 진단명 사전·금칙 표현에 걸리지 않는다."""
    terms = load_guard_terms()
    hits = [(f, where, text, [v.matched for v in vs])
            for f, where, text in content.iter_content_sentences()
            if (vs := find_violations(text, terms))]
    assert hits == []


def test_poc1_08_content_sentences_have_no_digits():
    """spec 7장 / G-03: 숫자는 자리표시자로만 둔다."""
    hits = [(f, where, text) for f, where, text in content.iter_content_sentences()
            if re.search(r"\d", re.sub(r"\{\w+\}", "", text))]
    assert hits == []


def test_iter_content_sentences_skips_pattern_files(content_copy):
    """패턴 파일(guard_terms 등)은 문장이 아니므로 검사 대상이 아니다."""
    files = {f for f, _, _ in content.iter_content_sentences(content_copy)}
    assert "guard_terms.json" not in files


# ── 척도 설명 카드 (PoC1-04) ──────────────────────────


def test_poc1_04_cards_cover_all_defined_scale_ranges(definitions):
    """정의(2-2)에서 판정 기준(group)이 있는 모든 척도 × 범위 3개에 카드가 정확히 1장씩 있다."""
    cards = content.load_scale_cards(definitions=definitions)
    got = sorted((c["assessment"], c["scale"], c["range"]) for c in cards)
    want = sorted((code, scale, r) for code, d in definitions.items()
                  for scale, sd in d["scales"].items() if "group" in sd for r in RANGES)
    assert got == want


def test_poc1_04_cards_are_draft():
    """G-04: PoC에서는 모든 카드가 검수 전 초안이다."""
    assert {c["status"] for c in content.load_scale_cards()} == {"draft"}


def test_card_recommendation_within_range_level():
    """spec 7장: 카드 문장은 보고서 권고 수준(범위 이름)을 넘지 않는다."""
    over = []
    for c in content.load_scale_cards():
        text = " ".join([c["what_it_asks"], c["report_recommendation"], *c["behavior_examples"]])
        if c["range"] == "normal" and "권고" in text:
            over.append(c["id"])
        if c["range"] == "borderline" and re.search("전문|정밀", text):
            over.append(c["id"])
    assert over == []


def test_cards_reject_duplicate_combo(content_copy):
    _edit(content_copy, "scale_cards.json", lambda cs: cs + [{**cs[0], "id": "card.dup"}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy)


def test_cards_reject_duplicate_id(content_copy):
    _edit(content_copy, "scale_cards.json", lambda cs: cs + [{**cs[0], "scale": "other_scale"}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy)


def test_cards_reject_unknown_scale(content_copy, definitions):
    _edit(content_copy, "scale_cards.json", lambda cs: [{**cs[0], "scale": "no_such_scale"}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy, definitions=definitions)


def test_cards_reject_scale_without_group(content_copy, definitions):
    """판정하지 않는 척도(group 없음)의 카드는 연결될 수 없으므로 오류."""
    _edit(content_copy, "scale_cards.json", lambda cs: [{**cs[0], "scale": "total_competence"}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy, definitions=definitions)


def test_cards_reject_unknown_placeholder(content_copy):
    _edit(content_copy, "scale_cards.json", lambda cs: [{**cs[0], "position_text": "{t}점입니다."}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy)


def test_cards_reject_missing_field(content_copy):
    _edit(content_copy, "scale_cards.json", lambda cs: [{k: v for k, v in cs[0].items() if k != "title"}])
    with pytest.raises(ContentError):
        content.load_scale_cards(content_copy)


# ── 한 줄 요약 템플릿 (PoC1-03) ───────────────────────


def test_summary_templates_cover_four_conditions_exactly():
    whens = sorted((t["when"]["has_clinical"], t["when"]["has_borderline"])
                   for t in content.load_summary_templates())
    assert whens == [(False, False), (False, True), (True, False), (True, True)]


def test_summary_templates_reject_missing_condition(content_copy):
    _edit(content_copy, "summary_templates.json", lambda ts: ts[:-1])
    with pytest.raises(ContentError):
        content.load_summary_templates(content_copy)


def test_summary_templates_reject_overlap(content_copy):
    _edit(content_copy, "summary_templates.json", lambda ts: ts + [{**ts[0], "id": "sum.dup"}])
    with pytest.raises(ContentError):
        content.load_summary_templates(content_copy)


def test_summary_templates_reject_list_of_absent_range(content_copy):
    """임상이 없는 조건의 템플릿에서 {clinical_list}를 쓰면 빈 목록이 들어가므로 오류."""
    def fn(ts):
        for t in ts:
            if not t["when"]["has_clinical"]:
                t["text"] += " {clinical_list}"
        return ts
    _edit(content_copy, "summary_templates.json", fn)
    with pytest.raises(ContentError):
        content.load_summary_templates(content_copy)


# ── 용어사전 ─────────────────────────────────────────


def test_glossary_unique_ids_terms_and_aliases():
    entries = content.load_glossary()
    ids = [e["id"] for e in entries]
    words = [w for e in entries for w in [e["term"], *e["aliases"]]]
    assert len(ids) == len(set(ids))
    assert len(words) == len(set(words))


def test_glossary_rejects_duplicate_alias(content_copy):
    _edit(content_copy, "glossary.json", lambda es: es + [{**es[0], "id": "term.dup", "term": "새 용어"}])
    with pytest.raises(ContentError):
        content.load_glossary(content_copy)


# ── 위기 키워드·의도 키워드·2일차 문구 (PoC2-01, 03, 04) ──


def test_crisis_and_intent_keywords_load():
    assert content.load_crisis()["keywords"]
    assert all(content.load_intent_keywords()[k] for k in content.INTENT_KEYWORD_KEYS)


def test_crisis_channels_have_source_when_present():
    """spec 7장: 공공 상담 채널은 공식 출처·확인일과 함께만 적는다."""
    for ch in content.load_crisis()["channels"]:
        assert ch["source_url"] and ch["checked_at"]


@pytest.mark.parametrize("fn", [
    lambda d: {**d, "keywords": d["keywords"] + [d["keywords"][0]]},                           # id 중복
    lambda d: {**d, "keywords": [{**d["keywords"][0], "category": "other"}]},                  # 알 수 없는 category
    lambda d: {**d, "keywords": [{**d["keywords"][0], "type": "glob"}]},                       # 알 수 없는 type
    lambda d: {**d, "keywords": [{**d["keywords"][0], "type": "regex", "pattern": "(죽고"}]},  # 깨진 정규식
    lambda d: {k: v for k, v in d.items() if k != "message"},                                  # 필수 키 누락
], ids=["dup_id", "category", "type", "regex", "missing_key"])
def test_crisis_rejects_bad_format(content_copy, fn):
    _edit(content_copy, "crisis.json", fn)
    with pytest.raises(ContentError):
        content.load_crisis(content_copy)


@pytest.mark.parametrize("fn", [
    lambda d: {**d, "crisis": [{"id": "intent.cr.001", "pattern": "죽고", "type": "literal"}]},  # 위기는 crisis.json에
    lambda d: {k: v for k, v in d.items() if k != "explain"},                                   # 키 누락
    lambda d: {**d, "explain": d["explain"] + [{**d["explain"][0], "id": d["diagnosis"][0]["id"]}]},  # 파일 전체 id 중복
    lambda d: {**d, "explain": [{**d["explain"][0], "type": "regex", "pattern": "[뜻"}]},       # 깨진 정규식
], ids=["crisis_key", "missing_key", "dup_id", "regex"])
def test_intent_keywords_reject_bad_format(content_copy, fn):
    _edit(content_copy, "intent_keywords.json", fn)
    with pytest.raises(ContentError):
        content.load_intent_keywords(content_copy)


def test_m1_phrases_do_not_require_qa_keys(content_copy):
    """2일차 문구가 없어도 결과 화면(M1) 문구 로드는 통과한다."""
    _edit(content_copy, "phrases.json", lambda d: {k: v for k, v in d.items() if k not in content.QA_PHRASE_KEYS})
    assert content.load_phrases(content_copy)
    with pytest.raises(ContentError):
        content.load_phrases(content_copy, required=content.QA_PHRASE_KEYS)


def test_poc1_08_scan_includes_crisis_message():
    assert ("crisis.json", "message[0]") in {(f, w) for f, w, _ in content.iter_content_sentences()}


# ── 안전 응답·척도 표현 (PoC2-05) ────────────────────


def test_safe_responses_cover_each_kind():
    templates = content.load_safe_responses()
    for kind in content.SAFE_KINDS:
        general = [t for t in templates if kind in t["intents"] and not t["requires_scale"]]
        scale = [t for t in templates if kind in t["intents"] and t["requires_scale"]]
        assert len(general) == 1 and len(scale) <= 1, kind


@pytest.mark.parametrize("fn", [
    lambda ts: [t for t in ts if t["id"] != "safe.parenting"],                                   # 일반 템플릿 누락
    lambda ts: ts + [{**ts[0], "id": "safe.extra"}],                                             # 척도 템플릿 2개
    lambda ts: [{**t, "text": t["text"] + "{t}"} if t["id"] == "safe.diagnosis" else t for t in ts],  # 일반 템플릿에 숫자 자리
    lambda ts: [{**t, "text": t["text"] + "{percentile}"} if t["requires_scale"] else t for t in ts],  # 허용 밖 자리표시자
    lambda ts: [{**t, "intents": ["smalltalk"]} if t["id"] == "safe.diagnosis" else t for t in ts],     # 모르는 종류
], ids=["missing_general", "two_scale", "general_placeholder", "scale_placeholder", "unknown_kind"])
def test_safe_responses_reject_bad_format(content_copy, fn):
    _edit(content_copy, "safe_responses.json", fn)
    with pytest.raises(ContentError):
        content.load_safe_responses(content_copy)


def test_scale_terms_match_definition(definitions):
    assert content.load_scale_terms(definitions=definitions)


@pytest.mark.parametrize("fn", [
    lambda ts: ts + [{**ts[0], "id": "terms.dup"}],                                          # (assessment, scale) 중복
    lambda ts: [{**ts[0], "terms": ts[0]["terms"] + [ts[1]["terms"][0]]}] + ts[1:],           # 표현 중복
    lambda ts: ts + [{**ts[0], "id": "terms.x", "scale": "no_such_scale", "terms": ["새 표현"]}],
], ids=["dup_scale", "dup_term", "unknown_scale"])
def test_scale_terms_reject_bad_format(content_copy, definitions, fn):
    _edit(content_copy, "scale_terms.json", fn)
    with pytest.raises(ContentError):
        content.load_scale_terms(content_copy, definitions=definitions)


def test_qa_phrases_present():
    assert content.load_phrases(required=content.QA_PHRASE_KEYS)


def test_crisis_channels_are_sourced():
    """spec 7장: 공공 상담 채널은 공식 출처와 확인일을 함께 적는다."""
    channels = content.load_crisis()["channels"]
    assert channels
    for ch in channels:
        assert ch["source_url"].startswith("https://") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ch["checked_at"])


# ── 마스킹 낱말 예외 (PoC2-02) ───────────────────────


def test_name_word_exceptions_load():
    assert {e["word"] for e in content.load_name_word_exceptions()} >= {"인사", "지우"}


@pytest.mark.parametrize("fn", [
    lambda es: es + [{**es[0], "word": "새낱말"}],                    # id 중복
    lambda es: es + [{**es[0], "id": "nw.dup"}],                      # word 중복
    lambda es: [{**es[0], "keep_patterns": ["(인사"]}] + es[1:],     # 깨진 정규식
    lambda es: [{**es[0], "keep_patterns": []}] + es[1:],            # 패턴 없음
], ids=["dup_id", "dup_word", "regex", "empty"])
def test_name_word_exceptions_reject_bad_format(content_copy, fn):
    _edit(content_copy, "name_word_exceptions.json", fn)
    with pytest.raises(ContentError):
        content.load_name_word_exceptions(content_copy)
