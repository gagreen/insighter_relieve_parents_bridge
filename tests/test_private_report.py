"""회사 제공 원본 보고서를 옮긴 결과 (specs/poc.md 2-4-1). 파일이 없으면(공개 리포지토리) 건너뛴다.

B-1(숫자)·B-2(범위)·PoC1-02(백분위 없음)·G-09(식별 정보)를 이 결과에도 확인한다.
"""
import json

import pytest

from bridge import config, content, db, pipeline, results
from bridge.ingest.validate import validate_payload
from bridge.rules.ranges import judge
from conftest import REAL_PRIVATE_RESULTS_DIR

FILES = sorted(REAL_PRIVATE_RESULTS_DIR.glob("*.json")) if REAL_PRIVATE_RESULTS_DIR.exists() else []
pytestmark = pytest.mark.skipif(not FILES, reason="data/private/kcbcl_results/ 없음 (커밋하지 않는 데이터)")
DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]


def _results():
    return [json.loads(p.read_text(encoding="utf-8")) for p in FILES]


def _view(payload):
    return results.build_view(payload, DEF, content.load_scale_cards(), content.load_summary_templates(),
                              content.load_phrases())


def test_2_4_1_payload_matches_schema():
    for r in _results():
        assert validate_payload(r["payload"], r["assessment_code"]) == [], r["result_id"]


def test_b2_ranges_match_report_labels():
    off = [(r["result_id"], s["id"]) for r in _results() for s in r["payload"]["scores"]
           if "group" in DEF["scales"][s["scale"]] and judge(s["scale"], s["t"], DEF) != s["range"]]
    assert off == []


def test_b1_view_numbers_copied_from_payload():
    for r in _results():
        view = _view(r["payload"])
        for s, item in zip(r["payload"]["scores"], view["items"]):
            assert (item["t"], item["percentile"]) == (s["t"], s["percentile"])


def test_poc1_02_no_percentile_means_floor_sentence_only_at_floor():
    """원보고서에 백분위가 없다. 하한(t_floor) 점수에만 하한 문장이 붙고 나머지는 숫자만."""
    phrases = content.load_phrases()
    for r in _results():
        for item in _view(r["payload"])["items"]:
            if item["t"] is None or item["percentile"] is not None:
                continue
            floor = results.t_floor(item["scale"], DEF)
            expected = phrases["percentile_unknown"] if item["t"] == floor else None
            assert item["percentile_text"] == expected, item["id"]


def test_g09_subject_stays_out_of_payload():
    for r in _results():
        text = json.dumps(r["payload"], ensure_ascii=False)
        assert r["subject"]["name"] not in text


def test_2_4_1_context_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRIVATE_RESULTS_DIR", REAL_PRIVATE_RESULTS_DIR)
    path = tmp_path / "t.db"
    assert db.init(path) == []
    conn = db.connect(path)
    for r in _results():
        ctx = pipeline.load_context(conn, r["result_id"])
        assert ctx.child_id == r["child_id"] and set(s["id"] for s in r["payload"]["scores"]) <= set(ctx.pack.items)
    conn.close()
