"""PoC1-01 범위 판정 [G-02] → B-2."""
import pytest

from bridge import config, db
from bridge.rules.ranges import direction, judge

DEF = {
    "groups": {
        "composite": {"direction": "higher_is_worse", "borderline_min": 60, "clinical_min": 63},
        "syndrome": {"direction": "higher_is_worse", "borderline_min": 60, "clinical_min": 70},
        "competence": {"direction": "lower_is_worse", "borderline_max": 40, "clinical_max": 36},
    },
    "scales": {
        "total": {"group": "composite"},
        "attention": {"group": "syndrome"},
        "total_competence": {"group": "competence"},
    },
}


@pytest.mark.parametrize("t, expected", [(59, "normal"), (60, "borderline"), (62, "borderline"), (63, "clinical")])
def test_poc1_01_composite_boundaries(t, expected):
    """PoC1-01: 종합척도 59/60/62/63."""
    assert judge("total", t, DEF) == expected


@pytest.mark.parametrize("t, expected", [(59, "normal"), (60, "borderline"), (69, "borderline"), (70, "clinical")])
def test_poc1_01_syndrome_boundaries(t, expected):
    """PoC1-01: 증후군 척도 59/60/69/70."""
    assert judge("attention", t, DEF) == expected


def test_poc1_01_syndrome_floor_50_is_normal():
    """PoC1-01: 증후군 척도 하한 50T."""
    assert judge("attention", 50, DEF) == "normal"


@pytest.mark.parametrize("t, expected", [(36, "clinical"), (40, "borderline"), (41, "normal")])
def test_poc1_01_lower_is_worse(t, expected):
    """PoC1-01: lower_is_worse — clinical_max, borderline_max, borderline_max+1."""
    assert judge("total_competence", t, DEF) == expected


@pytest.mark.parametrize("scale", ["total", "attention", "unknown_scale"])
def test_poc1_01_null_t_is_not_administered(scale):
    """PoC1-01: t가 null이면 not_administered (정의 유무와 무관)."""
    assert judge(scale, None, DEF) == "not_administered"


def test_poc1_01_undefined_scale_is_not_judged():
    """2-2: scales에 없는 척도는 판정하지 않는다(None)."""
    assert judge("emotional_instability", 66, DEF) is None


def test_poc1_01_direction_only_scale_is_not_judged():
    """2-2: group 없이 direction만 있는 척도는 판정하지 않는다(None)."""
    d = {**DEF, "scales": {**DEF["scales"], "sociability": {"direction": "lower_is_worse"}}}
    assert judge("sociability", 30, d) is None


def test_poc1_01_unknown_direction_raises():
    bad = {"groups": {"g": {"direction": "sideways"}}, "scales": {"x": {"group": "g"}}}
    with pytest.raises(ValueError):
        judge("x", 60, bad)


def test_poc1_01_b2_all_loaded_samples_match_report(loaded_db):
    """PoC1-01 / B-2: 적재된 샘플 전체에서 정의에 있는 척도의 판정 = payload range."""
    conn = loaded_db
    mismatches, checked = [], 0
    for row in conn.execute("SELECT result_id, assessment_code FROM assessment_results"):
        definition = db.get_definition(conn, row["assessment_code"])
        for score in db.get_payload(conn, row["result_id"])["scores"]:
            if "group" not in definition["scales"].get(score["scale"], {}):
                continue  # 판정 기준(group) 없는 척도는 대조 제외 (2-2)
            checked += 1
            got = judge(score["scale"], score["t"], definition)
            if got != score["range"]:
                mismatches.append((row["result_id"], score["id"], score["t"], score["range"], got))
    assert checked == len(list(config.RESULTS_DIR.glob("*.json"))) * 11   # 공개 샘플 × 판정 기준 있는 척도 11개
    assert mismatches == []


def test_2_2_direction_from_group_or_scale_entry():
    """2-2: direction은 group에서, group이 없으면 척도 항목에서 읽는다. 둘 다 없으면 None."""
    d = {**DEF, "scales": {**DEF["scales"], "sociability": {"direction": "lower_is_worse"}}}
    assert direction("attention", d) == "higher_is_worse"
    assert direction("total_competence", d) == "lower_is_worse"
    assert direction("sociability", d) == "lower_is_worse"
    assert direction("unknown_scale", d) is None
