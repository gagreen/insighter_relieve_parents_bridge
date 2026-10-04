"""결과 view model: PoC1-02 숫자 표시(B-1), PoC1-05 미실시, PoC1-06 기준선, PoC1-07 고정 문구."""
import copy
import json
import re

import pytest

from bridge import config, content, results
from bridge.content import ContentError

CARDS = content.load_scale_cards()
TEMPLATES = content.load_summary_templates()
PHRASES = content.load_phrases()
DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
SAMPLES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.RESULTS_DIR.glob("*.json"))]
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))


def _view(payload, definition=DEF):
    return results.build_view(payload, definition, CARDS, TEMPLATES, PHRASES)


BASE_VIEW = _view(BASE["payload"])


def _item(scale, view=BASE_VIEW):
    return next(i for i in view["items"] if i["scale"] == scale)


def _generated_texts(item):
    """코드가 content로 만든 문장(보고서 원문 제외)."""
    texts = [item["percentile_text"], item["direction_note"], item["status_text"]]
    if item["explanation"]["kind"] == "card":
        texts += list(content.card_sentences(item["explanation"]["card"]))
    return [t for t in texts if t]


# ── PoC1-02 / B-1 ────────────────────────────────────


def test_b1_numbers_copied_from_payload_all_samples():
    """B-1: 샘플 전체에서 화면의 T점수·백분위는 payload 값 그대로, rank_from_top = 100 − 백분위."""
    mismatches = []
    for r in SAMPLES:
        src = {s["id"]: s for s in r["payload"]["scores"]}
        for item in _view(r["payload"])["items"]:
            s = src[item["id"]]
            if (item["t"], item["percentile"]) != (s["t"], s["percentile"]):
                mismatches.append((r["result_id"], item["id"]))
            if item["rank_from_top"] is not None and item["rank_from_top"] != 100 - s["percentile"]:
                mismatches.append((r["result_id"], item["id"], "rank"))
    assert mismatches == []


def test_b1_generated_text_numbers_belong_to_item_all_samples():
    """B-1 / G-03: 생성 문장 속 숫자는 모두 그 항목의 {t, 백분위, 100−백분위} 중 하나다."""
    bad = []
    for r in SAMPLES:
        view = _view(r["payload"])
        for text in [view["notice"], view["summary"]["text"]]:
            if re.search(r"\d", text):
                bad.append((r["result_id"], text))
        for item in view["items"]:
            allowed = {str(v) for v in (item["t"], item["percentile"], item["rank_from_top"]) if v is not None}
            for text in _generated_texts(item):
                if extra := set(re.findall(r"\d+", text)) - allowed:
                    bad.append((r["result_id"], item["id"], text, extra))
    assert bad == []


def test_poc1_02_percentile_text_higher_is_worse():
    """PoC1-02: higher_is_worse → '상위 약 {100−p}%'. 주의집중 문제 p=95 → 상위 약 5%."""
    item = _item("attention")
    assert item["rank_from_top"] == 5
    assert "상위 약 5%" in item["percentile_text"]
    assert item["direction_note"] is None


def test_poc1_02_percentile_text_lower_is_worse():
    """PoC1-02: lower_is_worse → '하위 약 {p}%' + 방향 안내. 총 사회능력 p=16."""
    item = _item("total_competence")
    assert item["direction"] == "lower_is_worse"
    assert item["rank_from_top"] is None
    assert "하위 약 16%" in item["percentile_text"]
    assert "상위" not in item["percentile_text"]
    assert item["direction_note"] == PHRASES["direction_note_lower"]


def test_poc1_02_percentile_null_uses_floor_phrase():
    """PoC1-02: 백분위 null + T 있음(비행 50T) → 하한 설명 문장, 숫자 없음."""
    item = _item("delinquent")
    assert (item["t"], item["percentile"]) == (50, None)
    assert item["percentile_text"] == PHRASES["percentile_unknown"]


def _with_score(scale, **kw):
    payload = copy.deepcopy(BASE["payload"])
    for s in payload["scores"]:
        if s["scale"] == scale:
            s.update(kw)
    return payload


@pytest.mark.parametrize("scale, t", [("attention", 66), ("internalizing", 61)])
def test_poc1_02_percentile_null_above_floor_has_no_sentence(scale, t):
    """2026-10-05: 원보고서에 백분위가 없을 때(T가 하한이 아님) 하한 문장을 쓰지 않고 숫자만 둔다."""
    item = _item(scale, _view(_with_score(scale, t=t, percentile=None)))
    assert (item["t"], item["percentile_text"], item["rank_from_top"]) == (t, None, None)


def test_poc1_02_floor_comes_from_definition():
    """G-02: 하한값은 정의의 t_floor에서 읽는다(하드코딩 금지)."""
    d = copy.deepcopy(DEF)
    d["groups"]["syndrome"]["t_floor"] = 55
    item = _item("delinquent", _view(BASE["payload"], d))
    assert (item["t"], item["percentile_text"]) == (50, None)


def test_poc1_02_definition_has_syndrome_floor():
    assert DEF["groups"]["syndrome"]["t_floor"] == 50
    assert "t_floor" not in DEF["groups"]["composite"]


def test_poc1_02_no_direction_scale_has_numbers_only():
    """PoC1-02: direction 없는 척도는 백분위 문장 없이 숫자만."""
    d = copy.deepcopy(DEF)
    del d["scales"]["total_competence"]
    item = _item("total_competence", _view(BASE["payload"], d))
    assert item["percentile"] == 16
    assert item["percentile_text"] is None


# ── PoC1-05 ──────────────────────────────────────────


def test_poc1_05_not_administered_shown_with_report_text():
    """PoC1-05: 미실시 항목을 숨기지 않고 '미실시' + 보고서 원문 그대로."""
    item = _item("sex_problems")
    assert item["status"] == "not_administered"
    assert item["range_label"] == "미실시"
    assert item["status_text"] == PHRASES["not_administered"]
    assert item["percentile_text"] is None
    originals = {f["id"]: f["text"] for f in BASE["payload"]["findings"]}
    assert item["explanation"]["texts"] == [originals["IV.sex_problems.note"]]


def test_poc1_05_no_items_hidden_all_samples():
    for r in SAMPLES:
        view = _view(r["payload"])
        assert [i["id"] for i in view["items"]] == [s["id"] for s in r["payload"]["scores"]]


# ── PoC1-06 ──────────────────────────────────────────


def test_poc1_06_thresholds_from_definition():
    """PoC1-06 / G-02: 기준선은 정의에서 읽는다. 정의를 바꾸면 결과도 바뀐다."""
    assert _item("total")["thresholds"] == [
        {"value": 60, "range": "borderline", "label": "관찰 권고 범위"},
        {"value": 63, "range": "clinical", "label": "전문 상담 권고 범위"},
    ]
    assert [t["value"] for t in _item("attention")["thresholds"]] == [60, 70]
    d = copy.deepcopy(DEF)
    d["groups"]["composite"]["clinical_min"] = 65
    assert [t["value"] for t in _item("total", _view(BASE["payload"], d))["thresholds"]] == [60, 65]


def test_poc1_06_lower_is_worse_thresholds():
    d = copy.deepcopy(DEF)
    d["groups"]["competence"] = {"direction": "lower_is_worse", "borderline_max": 40, "clinical_max": 36}
    d["scales"]["total_competence"] = {"group": "competence"}
    assert [(t["value"], t["range"]) for t in results.thresholds("total_competence", d)] == \
        [(40, "borderline"), (36, "clinical")]


def test_poc1_06_scale_without_group_has_no_thresholds():
    """PoC1-06: group 없는 척도(정서불안정)는 기준선 없이 T 위치만."""
    item = _item("emotional_instability")
    assert item["thresholds"] is None
    assert item["range"] is None and item["range_label"] is None
    assert item["explanation"]["kind"] == "report_text"


# ── PoC1-07, G-09 ────────────────────────────────────


def test_poc1_07_fixed_notice():
    assert BASE_VIEW["notice"] == "선별 검사이며 진단이 아닙니다."


def test_g09_view_has_no_subject_fields_all_samples():
    """G-09: view model에 식별 정보(이름·생년월일)가 들어가지 않는다."""
    leaks = []
    for r in SAMPLES:
        dumped = json.dumps(_view(r["payload"]), ensure_ascii=False)
        for key in ("name", "birth_date"):
            if r["subject"].get(key) and r["subject"][key] in dumped:
                leaks.append((r["result_id"], key))
    assert leaks == []


# ── phrases.json 형식 ────────────────────────────────


@pytest.fixture
def content_copy(tmp_path):
    import shutil
    dst = tmp_path / "content"
    shutil.copytree(config.CONTENT_DIR, dst)
    return dst


def _edit_phrases(dir_, fn):
    path = dir_ / "phrases.json"
    path.write_text(json.dumps(fn(json.loads(path.read_text(encoding="utf-8"))), ensure_ascii=False),
                    encoding="utf-8")


def test_phrases_reject_missing_key(content_copy):
    _edit_phrases(content_copy, lambda p: {k: v for k, v in p.items() if k != "percentile_unknown"})
    with pytest.raises(ContentError):
        content.load_phrases(content_copy)


def test_phrases_reject_unknown_placeholder(content_copy):
    _edit_phrases(content_copy, lambda p: {**p, "percentile_unknown": "{t}점입니다."})
    with pytest.raises(ContentError):
        content.load_phrases(content_copy)
