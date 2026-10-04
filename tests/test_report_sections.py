"""PoC1-09 보고서 순서 배치 [G-03, G-12] → B-1."""
import copy
import json

from bridge import config, content, results

CARDS = content.load_scale_cards()
TEMPLATES = content.load_summary_templates()
PHRASES = content.load_phrases()
DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
SAMPLES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.RESULTS_DIR.glob("*.json"))]
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
REPORT_ORDER = ["H", "I", "II", "III", "IV", "V", "VI", "VII", "C"]


def _view(payload, definition=DEF):
    return results.build_view(payload, definition, CARDS, TEMPLATES, PHRASES)


def _placed_ids(view):
    return [b["id"] for s in view["sections"] for b in s["blocks"] if b["kind"] != "subgroup"]


def _section(view, key):
    return next(s for s in view["sections"] if s["key"] == key)


def test_poc1_09_definition_sections_follow_report():
    assert [s["key"] for s in DEF["report_sections"]] == REPORT_ORDER
    groups = _section({"sections": DEF["report_sections"]}, "III")["subgroups"]
    assert [g["title"] for g in groups] == ["내재화 증후군", "혼합 증후군", "외현화 증후군"]


def test_poc1_09_base_sample_in_report_order_although_payload_is_not():
    """035의 findings 배열은 II.summary → IV → H → V … 순서지만, 화면은 보고서 섹션 순서다."""
    payload_prefixes = list(dict.fromkeys(f["id"].split(".")[0] for f in BASE["payload"]["findings"]))
    assert payload_prefixes[:3] == ["II", "IV", "H"]
    assert [s["key"] for s in _view(BASE["payload"])["sections"]] == REPORT_ORDER


def test_poc1_09_section_order_all_samples():
    for r in SAMPLES:
        keys = [s["key"] for s in _view(r["payload"])["sections"]]
        assert keys == [k for k in REPORT_ORDER if k in keys], r["result_id"]


def test_poc1_09_scores_then_findings_in_payload_order():
    view = _view(BASE["payload"])
    blocks = _section(view, "IV")["blocks"]
    assert [b["id"] for b in blocks] == ["IV.emotional_instability", "IV.sex_problems",
                                         "IV.emotional_instability.note", "IV.sex_problems.note"]
    v_ids = [f["id"] for f in BASE["payload"]["findings"] if f["id"].startswith("V.")]
    assert [b["id"] for b in _section(view, "V")["blocks"]] == v_ids


def test_poc1_09_subgroups_follow_definition():
    blocks = _section(_view(BASE["payload"]), "III")["blocks"]
    assert [(b["kind"], b.get("title") or b["id"]) for b in blocks] == [
        ("subgroup", "내재화 증후군"), ("score", "III.withdrawn"), ("score", "III.somatic"), ("score", "III.anxdep"),
        ("subgroup", "혼합 증후군"), ("score", "III.socimm"), ("score", "III.thought"), ("score", "III.attention"),
        ("subgroup", "외현화 증후군"), ("score", "III.delinquent"), ("score", "III.aggressive"),
    ]


def test_poc1_09_every_item_exactly_once_all_samples():
    """누락·중복 0건 (숨기지 않음)."""
    for r in SAMPLES:
        payload = r["payload"]
        expected = [s["id"] for s in payload["scores"]] + [f["id"] for f in payload["findings"]]
        placed = _placed_ids(_view(payload))
        assert sorted(placed) == sorted(expected), r["result_id"]


def test_poc1_09_unknown_prefix_goes_to_other_section_last():
    payload = copy.deepcopy(BASE["payload"])
    payload["findings"].append({"id": "Z.extra", "type": "note", "section": "새 섹션", "scale": None, "text": "추가"})
    sections = _view(payload)["sections"]
    assert (sections[-1]["key"], sections[-1]["title"]) == ("_other", "기타")
    assert [b["id"] for b in sections[-1]["blocks"]] == ["Z.extra"]


def test_poc1_09_without_report_sections_keeps_payload_order():
    d = {k: v for k, v in DEF.items() if k != "report_sections"}
    sections = _view(BASE["payload"], d)["sections"]
    assert len(sections) == 1 and sections[0]["title"] is None
    payload = BASE["payload"]
    assert _placed_ids({"sections": sections}) == \
        [s["id"] for s in payload["scores"]] + [f["id"] for f in payload["findings"]]


def test_b1_finding_heading_numbers_from_scores_all_samples():
    """B-1: 문장 제목의 T점수는 같은 scale의 payload scores 값이다."""
    for r in SAMPLES:
        t_by_scale = {s["scale"]: s["t"] for s in r["payload"]["scores"]}
        for s in _view(r["payload"])["sections"]:
            for b in s["blocks"]:
                if b["kind"] == "finding" and b["heading"]:
                    assert b["heading"]["t"] == t_by_scale[b["scale"]], (r["result_id"], b["id"])


def test_poc1_09_heading_only_when_score_is_in_another_section():
    view = _view(BASE["payload"])
    socimm = next(b for b in _section(view, "V")["blocks"] if b["id"] == "V.socimm")
    assert socimm["heading"] == {"item_id": "III.socimm", "name": "사회적 미성숙", "t": 80,
                                 "range_label": "전문 상담 권고 범위"}
    note = next(b for b in _section(view, "IV")["blocks"] if b["id"] == "IV.sex_problems.note")
    assert note["heading"] is None
    summary = _section(view, "II")["blocks"][-1]
    assert summary["id"] == "II.summary" and summary["heading"] is None


def test_poc1_09_finding_text_is_original():
    originals = {f["id"]: f["text"] for f in BASE["payload"]["findings"]}
    for s in _view(BASE["payload"])["sections"]:
        for b in s["blocks"]:
            if b["kind"] == "finding":
                assert b["text"] == originals[b["id"]]
                assert b["segments"] == [{"text": b["text"], "term_id": None}]   # 용어사전 없이 만들면 풀이 없음
