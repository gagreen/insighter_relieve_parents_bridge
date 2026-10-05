"""PoC1-03 한 줄 요약 조립, PoC1-04 척도 설명 카드 [G-04, G-11] → B-3."""
import ast
import json

import pytest

from bridge import config, content, db, results
from bridge.guard.terms import find_violations, load_guard_terms

TEMPLATES = content.load_summary_templates()
CARDS = content.load_scale_cards()
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
BASE_PAYLOAD = BASE["payload"]
BASE_DEF = json.loads((config.ASSESSMENT_TYPES_DIR / f"{BASE['assessment_code']}.json")
                      .read_text(encoding="utf-8"))["definition"]


def _score(scale):
    return next(s for s in BASE_PAYLOAD["scores"] if s["scale"] == scale)


def _link(scale):
    s = _score(scale)
    judged = results.judge_scores([s], BASE_DEF)[0]["range"]
    return results.link_card(s, judged, CARDS, BASE_PAYLOAD["findings"], BASE_DEF, BASE_PAYLOAD["assessment"])


# ── PoC1-03 ──────────────────────────────────────────


@pytest.mark.parametrize("ranges, template_id", [
    (["normal", "normal"], "sum.none"),
    (["normal", "borderline"], "sum.borderline"),
    (["clinical", "normal"], "sum.clinical"),
    (["clinical", "borderline"], "sum.both"),
])
def test_poc1_03_template_selection(ranges, template_id):
    """PoC1-03: 임상 존재 여부 × 준임상 존재 여부로 템플릿 1개를 고른다."""
    judged = [{"id": f"s{i}", "name": f"척도{i}", "range": r} for i, r in enumerate(ranges)]
    assert results.summarize(judged, TEMPLATES)["template_id"] == template_id


def test_poc1_03_placeholders_filled_with_payload_names():
    """PoC1-03: 자리표시자는 payload의 척도 이름으로만 채운다 (기준 샘플 035)."""
    summary = results.summarize(results.judge_scores(BASE_PAYLOAD["scores"], BASE_DEF), TEMPLATES)
    assert summary["template_id"] == "sum.both"
    for name in ["외현화 문제", "총 문제행동", "사회적 미성숙", "주의집중 문제", "공격성"]:
        assert name in summary["text"]
    assert "{" not in summary["text"]


def test_poc1_03_undefined_and_not_administered_excluded():
    """정의 없는 척도(정서불안정)·미실시(성문제)는 요약 조건과 이름 목록에서 빠진다."""
    judged = results.judge_scores(BASE_PAYLOAD["scores"], BASE_DEF)
    by_scale = {j["scale"]: j["range"] for j in judged}
    assert by_scale["emotional_instability"] is None
    assert by_scale["sex_problems"] == "not_administered"
    text = results.summarize(judged, TEMPLATES)["text"]
    assert "정서불안정" not in text and "성문제" not in text


def test_poc1_03_results_module_does_not_use_llm():
    """PoC1-03 / G-04: 요약·카드 조립은 LLM을 호출하지 않는다."""
    tree = ast.parse((config.ROOT / "src/bridge/results.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    assert not {m for m in imported if "anthropic" in m or m.endswith("llm")}


# ── PoC1-04 ──────────────────────────────────────────


def test_poc1_04_card_linked_with_draft_label():
    """PoC1-04 / G-11: (scale, range) 카드 1장을 붙이고 draft면 '초안(검수 전)' 표시."""
    linked = _link("attention")
    assert linked["kind"] == "card"
    assert linked["card"]["id"] == "card.KCBCL_4_17.attention.borderline"
    assert linked["label"] == "초안(검수 전)"


def test_poc1_04_reviewed_card_gets_reviewed_label():
    cards = [{**c, "status": "reviewed"} for c in CARDS]
    s = _score("attention")
    linked = results.link_card(s, "borderline", cards, [], BASE_DEF, BASE_PAYLOAD["assessment"])
    assert linked["label"] == "검수된 설명"


def test_poc1_04_no_card_points_to_report_sections():
    """PoC1-04 (2026-10-05): 카드가 없는 조합(정의 없는 정서불안정)은 원문을 다시 싣지 않고 원문이 있는 섹션을 안내한다."""
    linked = _link("emotional_instability")
    assert linked["kind"] == "report_ref"
    assert linked["finding_ids"] == ["IV.emotional_instability.note", "V.emotional_instability", "VII.3"]
    assert linked["section_titles"] == ["Ⅳ. 특수 척도", "Ⅴ. 주요 관찰 소견", "Ⅶ. 보호자 참고 의견"]
    assert "texts" not in linked


def test_poc1_04_not_administered_points_to_report_sections():
    linked = _link("sex_problems")
    assert linked["kind"] == "report_ref"
    assert linked["finding_ids"] == ["IV.sex_problems.note"]
    assert linked["section_titles"] == ["Ⅳ. 특수 척도"]


def test_poc1_04_render_card_fills_name_and_label_only():
    rendered = _link("socimm")["card"]
    assert "사회적 미성숙" in rendered["position_text"]
    assert "전문 상담 권고 범위" in rendered["position_text"]
    assert not [t for t in content.card_sentences(rendered) if "{" in t]


def test_b3_assembled_summary_and_cards_clean_all_samples(loaded_db):
    """B-3: 적재된 샘플 전체의 조립된 한 줄 요약·카드 문장에 진단명·금칙 표현 0건."""
    terms = load_guard_terms()
    hits, checked = [], 0
    for row in loaded_db.execute("SELECT result_id, assessment_code FROM assessment_results"):
        definition = db.get_definition(loaded_db, row["assessment_code"])
        payload = db.get_payload(loaded_db, row["result_id"])
        judged = results.judge_scores(payload["scores"], definition)
        texts = [results.summarize(judged, TEMPLATES)["text"]]
        for s, j in zip(payload["scores"], judged):
            linked = results.link_card(s, j["range"], CARDS, payload["findings"], definition, payload["assessment"])
            if linked["kind"] == "card":
                texts += list(content.card_sentences(linked["card"]))
        for text in texts:
            checked += 1
            assert "{" not in text, (row["result_id"], text)
            if vs := find_violations(text, terms):
                hits.append((row["result_id"], text, [v.matched for v in vs]))
    assert checked > 100
    assert hits == []
