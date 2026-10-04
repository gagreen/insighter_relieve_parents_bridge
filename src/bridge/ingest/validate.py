"""payload 저장 전 검사별 JSON Schema 검증 (CLAUDE.md 8-1)."""
import json
from functools import cache

import jsonschema

from bridge import config


@cache
def _validator(assessment_code: str) -> jsonschema.protocols.Validator:
    # 검사 코드 → 스키마 파일 이름 규칙만 쓴다. 검사별 분기 없음(G-12).
    path = config.SCHEMAS_DIR / f"{assessment_code.lower()}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def validate_payload(payload: dict, assessment_code: str) -> list[str]:
    """오류 메시지 목록을 돌려준다. 빈 목록이면 통과."""
    try:
        validator = _validator(assessment_code)
    except FileNotFoundError:
        return [f"스키마 없음: {assessment_code}"]
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in validator.iter_errors(payload)
    ]
