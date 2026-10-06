"""프롬프트 파일 [CLAUDE.md 7장, G-02, G-12]."""
import json
import re

from bridge import config, llm
from bridge.pipeline import INTENT_CODES

DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))


def test_prompt_versions_point_to_files():
    for stage, version in config.PROMPT_VERSIONS.items():
        assert re.fullmatch(rf"{stage}_v\d+", version)
        assert (config.PROMPTS_DIR / f"{version}.md").exists()


def test_intent_prompt_names_all_intent_codes():
    """spec 2-5의 의도 코드와 프롬프트가 맞아야 한다."""
    prompt = llm.load_prompt(config.PROMPT_VERSIONS["intent"])
    assert INTENT_CODES == ("explain", "diagnosis", "parenting", "crisis", "out_of_scope", "consult_prep")
    for code in INTENT_CODES:
        assert f"`{code}`" in prompt


def test_answer_prompt_is_assessment_agnostic():
    """G-12 / G-02: 척도 키·척도 이름·기준값은 근거로만 들어간다."""
    prompt = llm.load_prompt(config.PROMPT_VERSIONS["answer"])
    scale_keys = set(DEF["scales"])
    names = {s["name"] for s in BASE["payload"]["scores"]}
    cutoffs = {str(v) for g in DEF["groups"].values() for k, v in g.items() if k != "direction"}
    assert not [k for k in scale_keys if re.search(rf"\b{k}\b", prompt)]
    assert not [n for n in names if n in prompt]
    assert not cutoffs & set(re.findall(r"\d+", prompt))


def test_answer_prompt_requires_output_fields():
    prompt = llm.load_prompt(config.PROMPT_VERSIONS["answer"])
    for field in ("answerable", "answer", "evidence_ids", "note_question"):
        assert f"`{field}`" in prompt


def test_organize_prompt_names_all_brief_types():
    from bridge.notes import BRIEF_TYPES
    prompt = llm.load_prompt(config.PROMPT_VERSIONS["organize"])
    for code in BRIEF_TYPES:
        assert f"`{code}`" in prompt
    assert "source_item_ids" in prompt


def test_answer_v3_is_current_and_covers_loss_fixes():
    """답 손실 개선(spec PoC2-07, 2026-10-06): 예시 숫자·차이 계산 금지, gap, id 복사, 재생성 사유."""
    assert config.PROMPT_VERSIONS["answer"] == "answer_v3"
    prompt = llm.load_prompt("answer_v3")
    for phrase in ("`gap`", "<retry_feedback>", "글자 그대로", "예시"):
        assert phrase in prompt


def test_old_answer_prompts_are_kept():
    """기존 버전 파일은 고치지 않고 남긴다 (CLAUDE.md 7장)."""
    for version in ("answer_v1", "answer_v2"):
        assert llm.load_prompt(version).strip()
