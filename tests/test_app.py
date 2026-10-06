"""Streamlit 데모 (specs/poc.md 5장) [G-04, G-11, PoC1-05·06·07, PoC2-03]. LLM은 가짜 클라이언트로 바꾼다."""
import json
import re
import sys

import pytest
from streamlit.testing.v1 import AppTest

from bridge import config, llm
from llm_fakes import FakeClient, fake_response

sys.path.insert(0, str(config.ROOT / "app"))
import components  # noqa: E402

APP = str(config.ROOT / "app" / "main.py")
DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
PAYLOAD = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))["payload"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.delenv("BRIDGE_RESULT_ID", raising=False)   # 로컬 .env의 데모 결과 선택과 무관하게 기준 샘플로 연다
    monkeypatch.setattr(llm, "get_client", lambda *a, **k: FakeClient())   # LLM 호출이 생기면 실패
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    els = [*at.markdown, *at.caption, *at.info, *at.subheader, *at.text, *at.code]
    return "\n".join(str(e.value) for e in els)


def test_5_results_tab(app):
    text = _texts(app)
    assert "선별 검사이며 진단이 아닙니다" in text                   # PoC1-07
    assert len(app.subheader) >= len(PAYLOAD["scores"])               # 항목을 숨기지 않음 (PoC1-05)
    assert "미실시" in text and "초안(검수 전)" in text                # G-04, G-11


def test_poc1_09_results_tab_in_report_order(app):
    """섹션 제목이 보고서 순서대로, 점수와 원문이 한 화면에 함께 나온다. 맨 아래 원문 모음은 없다."""
    text = _texts(app)
    titles = [s["title"] for s in DEF["report_sections"]]
    positions = [text.index(f"### {t}") for t in titles]
    assert positions == sorted(positions)
    assert "원본 보고서 문장 보기" not in [e.label for e in app.expander]


def test_poc1_10_glossary_and_poc1_11_save(app):
    """낱말 풀이 목록과 해석 표현의 상담 질문 저장 → 질문 노트에 들어간다 (LLM 없음)."""
    assert any(e.label.startswith("낱말 풀이") and "초안(검수 전)" in e.label for e in app.expander)
    button = next(b for b in app.button if b.key.startswith("save:"))
    button.click().run()
    assert not app.exception, app.exception
    text = _texts(app)
    assert "상담 질문으로 저장했습니다" in text
    assert "질문 노트 (1)" in text and "표현이 무슨 뜻인지 궁금합니다" in text


def test_5_safe_response_and_note(app):
    app.chat_input[0].set_value("ADHD인가요?").run()
    assert not app.exception, app.exception
    text = _texts(app)
    assert "안전 응답" in text and "ADHD인가요?" in text
    assert "질문 노트 (1)" in text
    assert "AI에게 보낸 문장" in text


def test_poc2_03_crisis_disables_input(app):
    app.chat_input[0].set_value("아이가 죽고 싶다고 해요").run()
    assert app.chat_input[0].disabled


def test_5_brief_button(app, monkeypatch):
    app.chat_input[0].set_value("ADHD인가요?").run()
    # 질문 정리 LLM이 두 번 모두 깨진 응답 → 원래 질문 목록으로 브리프 (화면이 멈추지 않음)
    fake = FakeClient(fake_response("not json"), fake_response("not json"))
    monkeypatch.setattr(llm, "get_client", lambda *a, **k: fake)
    app.button(key="make_brief").click().run()
    assert not app.exception, app.exception
    brief_text = "\n".join(c.value for c in app.code)
    assert "① 보호자 질문" in brief_text and "ADHD인가요?" in brief_text
    assert "자동 정리 실패" in brief_text and len(fake.calls) == 2


# ── 기준선 그래프 (PoC1-06, G-02) ───────────────────


def _item(scale, t, percentile=None):
    from bridge import content, results
    payload = {**PAYLOAD, "scores": [{**s, "t": t, "percentile": percentile} if s["scale"] == scale else s
                                      for s in PAYLOAD["scores"]]}
    view = results.build_view(payload, DEF, content.load_scale_cards(), content.load_summary_templates(),
                              content.load_phrases())
    return next(i for i in view["items"] if i["scale"] == scale)


def test_poc1_06_baseline_values_come_from_definition():
    svg = components.baseline_svg(_item("attention", 66, 95), DEF["range_labels"])
    group = DEF["groups"][DEF["scales"]["attention"]["group"]]
    assert re.findall(r'data-threshold="(\d+)"', svg) == [str(group["borderline_min"]), str(group["clinical_min"])]
    assert 'data-t="66"' in svg
    assert DEF["range_labels"]["borderline"] in svg


def test_poc1_06_scale_without_group_has_no_baselines():
    svg = components.baseline_svg(_item("emotional_instability", 66), DEF["range_labels"])
    assert "data-threshold" not in svg and 'data-t="66"' in svg


def test_poc1_05_not_administered_has_no_marker():
    svg = components.baseline_svg(_item("sex_problems", None), DEF["range_labels"])
    assert "data-t=" not in svg


# ── 결과 선택 (spec 2-4-1) ──────────────────────────


def test_2_4_1_result_selected_by_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("BRIDGE_RESULT_ID", "R-KCBCL_4_17-001")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert "R-KCBCL_4_17-001" in _texts(at)


def test_2_4_1_unknown_result_shows_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setenv("BRIDGE_RESULT_ID", "R-NONE")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    assert at.error and "R-NONE" in at.error[0].value
