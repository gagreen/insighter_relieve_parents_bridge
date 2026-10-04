"""초기 세팅 확인: 경로·샘플 데이터·스키마가 서로 맞는지 (CLAUDE.md 8-1, 8-4)."""
import json

import jsonschema
import pytest

from bridge import config


def test_config_paths_exist():
    for path in (config.RESULTS_DIR, config.ASSESSMENT_TYPES_DIR, config.SCHEMAS_DIR,
                 config.CONTENT_DIR, config.PROMPTS_DIR, config.BASE_SAMPLE_FILE):
        assert path.exists(), path


def test_default_model_is_priced():
    assert config.DEFAULT_MODEL in config.PRICES_PER_MTOK


@pytest.mark.parametrize("result_file", sorted(config.RESULTS_DIR.glob("*.json")), ids=lambda p: p.name)
def test_sample_payload_matches_schema(result_file):
    """8-1: 저장 전 검사별 JSON Schema 검증 — 샘플 100건 모두 통과해야 한다."""
    schema = json.loads((config.SCHEMAS_DIR / "kcbcl_4_17.schema.json").read_text(encoding="utf-8"))
    payload = json.loads(result_file.read_text(encoding="utf-8"))["payload"]
    jsonschema.validate(payload, schema)
