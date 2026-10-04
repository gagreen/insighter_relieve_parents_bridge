"""PoC2-01 입력 검증 [P-01]. 파이프라인의 첫 단계(마스킹 전)."""
from dataclasses import dataclass
from typing import Literal

from bridge import config, content


@dataclass(frozen=True)
class InputCheck:
    ok: bool
    reason: Literal["empty", "too_long"] | None = None
    message: str | None = None


def check_input(text: str, phrases: dict[str, str] | None = None,
                max_chars: int = config.MAX_INPUT_CHARS) -> InputCheck:
    """길이는 앞뒤 공백을 뺀 기준. 빈 입력은 처리하지 않고, 상한 초과는 나눠 질문하라고 안내한다."""
    stripped = text.strip()
    if stripped and len(stripped) <= max_chars:
        return InputCheck(ok=True)
    phrases = phrases or content.load_phrases(required=content.QA_PHRASE_KEYS)
    if not stripped:
        return InputCheck(False, "empty", phrases["input_empty"])
    return InputCheck(False, "too_long", phrases["input_too_long"].format(max_chars=f"{max_chars:,}"))
