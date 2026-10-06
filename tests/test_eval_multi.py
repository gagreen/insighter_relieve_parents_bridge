"""다샘플 평가 [specs/poc.md 6-2, G-03, G-12]. LLM은 모킹한다."""
import json
import re

import pytest

from bridge import config, pipeline
from eval import run
from llm_fakes import FakeClient


def _ctx(conn, sample_id):
    return pipeline.load_context(conn, run.result_id_of(sample_id))


def _tpl(slot, text="{scale_name} T점수 {t}점", id="T", type="explain", route="answer"):
    return run.Template(id, type, slot, text, route, [], "")


# ── 템플릿 채우기 ────────────────────────────────────


def test_6_2_fill_uses_view_values(loaded_db):
    """035: 준임상 중 T점수가 가장 높은 척도(주의집중 66, 공격성 66 → payload 순서가 앞선 주의집중)."""
    item = run.fill_template(_tpl("range:borderline"), _ctx(loaded_db, "035"))
    assert item.question == "주의집중 문제 T점수 66점"
    assert item.expected_evidence == ["III.attention"]
    assert (item.id, item.sample) == ("T@035", run.result_id_of("035"))


@pytest.mark.parametrize("slot, expected_id", [
    ("range:clinical", "III.socimm"),            # 80
    ("range:normal", "III.withdrawn"),           # 정상 중 최고 58
    ("highest", "III.socimm"),
    ("t_floor", "III.delinquent"),               # 50T, 백분위 null
    ("not_administered", "IV.sex_problems"),
    ("lower_is_worse", "I.sociability"),         # 역방향 척도 중 payload 첫 항목
])
def test_6_2_slot_selection_on_base_sample(loaded_db, slot, expected_id):
    text = "{scale_name}" if slot == "not_administered" else "{scale_name} {t}"
    assert run.fill_template(_tpl(slot, text), _ctx(loaded_db, "035")).expected_evidence == [expected_id]


def test_6_2_numbers_in_filled_questions_come_from_payload(loaded_db):
    """G-03: 질문 속 숫자는 그 샘플 payload의 T점수다 (선정 샘플 전체)."""
    templates = run.load_templates()
    for sample in run.select_samples():
        ctx = _ctx(loaded_db, sample["id"])
        scores = {s["id"]: s for s in ctx.payload["scores"]}
        for t in templates:
            item = run.fill_template(t, ctx)
            if item is None or "{t}" not in t.text:
                continue
            [sid] = item.expected_evidence
            assert re.findall(r"\d+", item.question.split("T점수")[-1])[0] == str(scores[sid]["t"])


def test_6_2_missing_slot_is_skipped(loaded_db):
    """준임상 척도가 없는 정상 샘플에서는 range:borderline 템플릿을 건너뛴다."""
    normal = next(s for s in run.select_samples() if s["tier"] == "정상")
    ctx = _ctx(loaded_db, normal["id"])
    if any(i["range"] == "borderline" for i in ctx.view["items"]):
        pytest.skip("선정된 정상 샘플에 준임상 척도가 있음")
    assert run.fill_template(_tpl("range:borderline"), ctx) is None


def test_6_2_slot_without_placeholders_is_same_question(loaded_db):
    item = run.fill_template(_tpl(None, "백분위가 뭐예요?"), _ctx(loaded_db, "035"))
    assert item.question == "백분위가 뭐예요?" and item.expected_evidence == []


def test_g12_template_slots_use_common_keys_only():
    """slot은 공통 키(range, direction, t_floor, 미실시)로만 정한다. 검사별 척도 키를 쓰지 않는다."""
    definition = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
    scale_keys = set(definition["scales"])
    for t in run.load_templates():
        assert t.slot is None or t.slot in run.SLOTS
        assert not any(k in (t.slot or "") for k in scale_keys)


# ── 샘플 선정 ───────────────────────────────────────


def test_6_2_select_samples_is_deterministic_and_covers_strata():
    a, b = run.select_samples(), run.select_samples()
    assert a == b and len(a) == 10
    ids = [s["id"] for s in a]
    assert len(set(ids)) == 10 and "035" in ids
    tiers = [s["tier"] for s in a]
    for tier in run.TIERS:
        assert tiers.count(tier) >= 2
    assert sum(s["risk_comment"] for s in a) >= 2
    assert all(s["reason"] for s in a)


def test_6_2_sample_meta_not_in_evidence(loaded_db):
    """sample_meta는 고르는 데만 쓴다. 근거 묶음(AI 입력)에 들어가지 않는다 (CLAUDE.md 8-4)."""
    ctx = _ctx(loaded_db, "035")
    assert "severity_tier" not in ctx.pack.text and "profile_type" not in ctx.pack.text


# ── 실행 ────────────────────────────────────────────


def test_6_2_run_multi_aggregates_and_records_skips(tmp_path):
    templates = [_tpl(None, "ADHD인가요?", id="T-DX", type="diagnosis", route="safe"),
                 _tpl("range:clinical", "{scale_name} 점수가 T점수 {t}점인데 병원에 가야 하나요?", id="T-DX2",
                      type="diagnosis", route="safe")]
    normal = next(s["id"] for s in run.select_samples() if s["tier"] == "정상")
    rep = run.run_multi(templates, ["035", normal], model=config.HAIKU, client=FakeClient(),
                        db_path=tmp_path / "m.db")
    assert rep.kind == "multi" and rep.result_ids == [run.result_id_of("035"), run.result_id_of(normal)]
    assert {r.item.id for r in rep.items} >= {"T-DX@035", "T-DX2@035", f"T-DX@{normal}"}
    assert all(r.turn.route == "safe" for r in rep.items)
    assert ("T-DX2", run.result_id_of(normal)) in rep.skipped        # 정상 샘플엔 임상 척도 없음
    md = run.render_markdown(rep)
    assert "## 2-2. 샘플별 결과" in md and "건너뜀" in md
    assert "R-1 직접 답" not in md                                    # 다샘플은 수동 채점 칸 없음


def test_6_2_multi_report_name(tmp_path):
    rep = run.run_multi([], ["035"], model=config.HAIKU, client=FakeClient(), db_path=tmp_path / "m.db")
    md, _ = run.write_report(rep, tmp_path)
    assert md.name.endswith(f"_{config.HAIKU}_{run.CURRENT_PROMPT_SET}_multi.md")


# ── 질문 정리 ───────────────────────────────────────


def test_organize_run_without_llm_falls_back(tmp_path):
    """API 오류면 노트 1건 = 항목 1개 (PoC2-11). 리포트에 수동 채점 칸이 있다."""
    import anthropic
    import httpx2
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    samples = tmp_path / "s.jsonl"
    samples.write_text(json.dumps({"id": "ORG-X", "saved_questions": ["ADHD인가요?", "숙제를 어떻게 도와줘야 하나요?"],
                                   "expected_items": 2, "note": ""}, ensure_ascii=False) + "\n", encoding="utf-8")
    md = run.run_organize(samples, model=config.HAIKU, client=FakeClient(err), db_path=tmp_path / "o.db")
    assert "ORG-X" in md and "fallback" in md
    assert "의미가 바뀐 질문: ___" in md and "빠진 질문: ___" in md
    assert "[diagnosis]" in md and "[parenting]" in md
