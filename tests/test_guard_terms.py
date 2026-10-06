"""진단명 사전·금칙 표현 검사기 [G-01] — PoC1-08(B-3)에서 만들고 PoC2-08(B-4)에서 재사용."""
import json

import pytest

from bridge import config
from bridge.guard.terms import CATEGORIES, find_violations, load_guard_terms

TERMS = load_guard_terms()


def _categories(text):
    return {v.category for v in find_violations(text, TERMS)}


def test_guard_terms_load_valid():
    ids = [t.id for t in TERMS]
    assert len(ids) == len(set(ids))
    assert {t.type for t in TERMS} <= {"literal", "regex"}
    assert {t.category for t in TERMS} == CATEGORIES  # 8개 category 모두 최소 1개


def test_guard_terms_invalid_regex_raises(tmp_path):
    path = tmp_path / "guard_terms.json"
    path.write_text(json.dumps([{"id": "x", "pattern": "(", "type": "regex", "category": "threat"}]))
    with pytest.raises(ValueError):
        load_guard_terms(path)


def test_guard_terms_unknown_category_raises(tmp_path):
    path = tmp_path / "guard_terms.json"
    path.write_text(json.dumps([{"id": "x", "pattern": "a", "type": "literal", "category": "etc"}]))
    with pytest.raises(ValueError):
        load_guard_terms(path)


@pytest.mark.parametrize("text, category", [
    ("ADHD일 수도 있어요.", "diagnosis_name"),
    ("자폐 성향이 보입니다.", "diagnosis_name"),
    ("우울증이 걱정됩니다.", "diagnosis_name"),
    ("틱이 있는 아이들에게서 보입니다.", "diagnosis_name"),
    ("발달장애와 관련이 있습니다.", "diagnosis_name"),
    ("주의력 문제의 가능성이 높습니다.", "diagnosis_possibility"),
    ("과잉행동이 의심됩니다.", "diagnosis_possibility"),
    ("놀이치료를 해 보세요.", "treatment"),
    ("치료가 필요해 보입니다.", "treatment"),
    ("약물을 고려해 볼 수 있습니다.", "medication"),
    ("콘서타를 많이 씁니다.", "medication"),
    ("정신건강의학과를 방문해 보세요.", "institution"),
    ("가까운 병원에 가 보세요.", "institution"),
    ("크면서 좋아질 거예요.", "prognosis"),
    ("시간이 지나면 나아질 수 있습니다.", "prognosis"),
    ("걱정하지 않으셔도 됩니다.", "reassurance"),
    ("이 정도면 괜찮아요.", "reassurance"),
    ("큰 문제 없습니다.", "reassurance"),
    ("심각한 수준입니다.", "threat"),
    ("지금 바로 시급하게 대응해야 합니다.", "threat"),
])
def test_guard_detects_each_category(text, category):
    """G-01: 진단명·진단 가능성·치료·약물·기관·예후·안심·위협 판단을 잡는다."""
    assert category in _categories(text)


@pytest.mark.parametrize("text", ["주의력 결핍 양상입니다.", "adhd 아닌가요", "과잉행동 장애"])
def test_guard_detects_spacing_and_case_variants(text):
    assert "diagnosis_name" in _categories(text)


@pytest.mark.parametrize("text", [
    "선별 검사이며 진단이 아닙니다.",
    "진단·치료에 관한 판단은 상담에서 다룹니다.",
    "이 결과만으로 진단을 내리지 않습니다.",
    "답한 사람의 관찰 상황에 따라 차이가 있을 수 있습니다.",
    "플라스틱 장난감을 던지는 모습",
])
def test_guard_allows_boundary_sentences(text):
    """3장 원칙: '진단'·'치료' 단어 자체는 허용한다(경계 안내에 필요)."""
    assert find_violations(text, TERMS) == []


@pytest.mark.parametrize("text", [
    "상위 약 1%에 해당하는 매우 높은 수준입니다.",
    "점수가 또래보다 상당히 높게 나왔습니다.",
    "이 영역의 점수(T=80)가 매우높아서",
    "사회능력 점수가 크게 낮습니다.",
])
def test_guard_detects_intensity_beyond_report(text):
    """G-01·7장: 보고서 권고 수준을 넘는 정도 표현은 위협 판단으로 본다(9장 미결 '응답 품질', 2026-10-06)."""
    assert "threat" in _categories(text)


@pytest.mark.parametrize("text", [
    "상위 약 1%에 해당하는 높은 점수입니다.",
    "점수가 높을수록 이런 모습이 많이 보고되었다는 뜻입니다.",
    "기준선 70보다 4점 높습니다.",
])
def test_guard_allows_plain_position(text):
    """정도 부사 없이 위치·방향만 말하는 문장은 허용한다."""
    assert find_violations(text, TERMS) == []


def test_guard_allows_all_scale_names_and_range_labels():
    """요약·카드에 그대로 들어가는 척도 이름·범위 이름은 걸리지 않아야 한다."""
    texts = set()
    for path in config.ASSESSMENT_TYPES_DIR.glob("*.json"):
        texts |= set(json.loads(path.read_text(encoding="utf-8"))["definition"]["range_labels"].values())
    for path in config.RESULTS_DIR.glob("*.json"):
        texts |= {s["name"] for s in json.loads(path.read_text(encoding="utf-8"))["payload"]["scores"]}
    flagged = {t: find_violations(t, TERMS) for t in texts}
    assert {t: v for t, v in flagged.items() if v} == {}
