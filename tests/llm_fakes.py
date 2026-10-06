"""단위 테스트용 가짜 Anthropic 클라이언트 (CLAUDE.md 12장: 단위 테스트에서 LLM은 모킹한다)."""
import json
from types import SimpleNamespace


def fake_response(text: str | dict, *, input_tokens=100, cache_write=0, cache_read=0, output_tokens=20,
                  thinking=False, stop_reason="end_turn"):
    if isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    content = [SimpleNamespace(type="thinking", thinking="")] if thinking else []
    content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(input_tokens=input_tokens, cache_creation_input_tokens=cache_write,
                            cache_read_input_tokens=cache_read, output_tokens=output_tokens)
    return SimpleNamespace(content=content, usage=usage, stop_reason=stop_reason)


class _Messages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("예상하지 않은 LLM 호출")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeClient:
    """create()에 넘긴 인자를 messages.calls에 기록하고, 준비한 응답(또는 예외)을 순서대로 돌려준다."""

    def __init__(self, *responses):
        self.messages = _Messages(responses)

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls


# ── OpenAI 호환 API (OpenAI, Gemini — specs/poc.md 6-3) ──


def fake_chat_response(text: str | dict | None, *, prompt_tokens=100, cached=0, completion_tokens=20,
                       finish_reason="stop", refusal=None):
    if isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    message = SimpleNamespace(content=text, refusal=refusal)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=cached))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], usage=usage)


class FakeOpenAIClient:
    """chat.completions.create()에 넘긴 인자를 calls에 기록하고, 준비한 응답(또는 예외)을 순서대로 돌려준다."""

    def __init__(self, *responses):
        self._completions = _Messages(responses)
        self.chat = SimpleNamespace(completions=self._completions)

    @property
    def calls(self) -> list[dict]:
        return self._completions.calls
