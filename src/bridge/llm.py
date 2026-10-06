"""LLM 호출 단일 진입점 [CLAUDE.md 9장, PoC2-13, P-05].

Anthropic SDK와 OpenAI SDK는 이 모듈만 import한다. 응답은 구조화 출력(JSON Schema)으로 받고, 마지막 system 블록에
캐시 지점을 둔다. 형식 검증은 호출자가 모델과 무관한 규칙으로 따로 한다(G-08).

다른 회사 모델(specs/poc.md 6-3)은 '<제공사>:<모델>' ID로 고르고 OpenAI 호환 API로 부른다. OpenAI SDK는 선택 설치
(`pip install -e '.[compare]'`)라 없으면 그 모델 호출만 LLMError가 된다.
"""
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache

import anthropic

try:
    import openai
except ImportError:  # 선택 설치 [compare]
    openai = None

from bridge import config

STAGES = ("intent", "answer", "organize")
_COMPAT_ERRORS = (openai.APIError,) if openai else ()   # SDK 재시도(P-05) 후에도 실패한 호출


class LLMError(Exception):
    """SDK 재시도(P-05) 후에도 실패한 호출."""


@dataclass(frozen=True)
class LLMResult:
    stage: str
    model: str
    prompt_version: str
    text: str | None          # 첫 text 블록 (thinking 블록은 건너뜀)
    stop_reason: str
    input_tokens: int         # 캐시를 거치지 않은 입력
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


@lru_cache(maxsize=1)
def get_client(api_key: str | None = None) -> anthropic.Anthropic:
    """재시도는 SDK에 맡긴다(연결 오류·408·409·429·5xx). P-05 축소: 1회."""
    return anthropic.Anthropic(api_key=api_key, max_retries=config.API_RETRY_LIMIT)


def provider_of(model: str) -> tuple[str, str]:
    """('anthropic', 모델) 또는 (PROVIDERS의 제공사, 그 제공사의 모델 이름). 모델 이름 안의 ':'는 그대로 둔다."""
    prefix, sep, name = model.partition(":")
    if sep and prefix in config.PROVIDERS:
        return prefix, name
    return "anthropic", model


@lru_cache(maxsize=None)
def get_compat_client(provider: str):
    """OpenAI 호환 클라이언트. 재시도는 SDK에 맡긴다(P-05 축소: 1회). 키가 없으면 LLMError."""
    if openai is None:
        raise LLMError(f"{provider} 호출에 openai SDK가 필요합니다 (pip install -e '.[compare]')")
    spec = config.PROVIDERS[provider]
    if not (api_key := os.environ.get(spec["key_env"])):
        raise LLMError(f"{provider} 호출 실패: 인증 정보 없음 ({spec['key_env']} 확인)")
    return openai.OpenAI(api_key=api_key, base_url=spec["base_url"], max_retries=config.API_RETRY_LIMIT)


def tagged(tag: str, body: str) -> str:
    """보호자 입력을 별도 태그 영역에 넣는다(G-08). 입력 속 꺾쇠는 전각으로 바꿔 태그를 만들 수 없게 한다."""
    body = body.replace("<", "＜").replace(">", "＞")
    return f"<{tag}>\n{body}\n</{tag}>"


def parse_json_object(text: str | None) -> dict | None:
    """JSON 객체가 아니면 None (형식 검증의 첫 단계, 모델과 무관)."""
    try:
        value = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def load_prompt(version: str) -> str:
    path = config.PROMPTS_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 없음: {path}")
    return path.read_text(encoding="utf-8")


def cost_usd(model: str, input_tokens: int, cache_write_tokens: int, cache_read_tokens: int,
             output_tokens: int) -> float:
    """config 단가(100만 토큰당)로 계산한다. 캐시 쓰기 1.25배, 캐시 읽기는 cache_read 단가(없으면 0.1배)."""
    price = config.PRICES_PER_MTOK[model]
    cache_read_price = price.get("cache_read", price["input"] * config.CACHE_READ_MULTIPLIER)
    total = (input_tokens * price["input"]
             + cache_write_tokens * price["input"] * config.CACHE_WRITE_MULTIPLIER
             + cache_read_tokens * cache_read_price
             + output_tokens * price["output"])
    return total / 1_000_000


def _request(stage: str, model: str, system_parts: list[str], user_text: str, schema: dict) -> dict:
    system = [{"type": "text", "text": text} for text in system_parts]
    system[-1]["cache_control"] = {"type": "ephemeral"}
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if effort := config.MODEL_EFFORT.get(model):
        output_config["effort"] = effort
    return {
        "model": model,
        "max_tokens": config.MAX_TOKENS[stage],
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
        "output_config": output_config,
    }


def _compat_request(stage: str, model: str, system_parts: list[str], user_text: str, schema: dict) -> dict:
    """OpenAI 호환 Chat Completions. system은 정책 → 근거 순서 그대로 한 메시지(제공사의 자동 접두어 캐시)."""
    request = {
        "model": provider_of(model)[1],
        "messages": [{"role": "system", "content": "\n\n".join(system_parts)},
                     {"role": "user", "content": user_text}],
        "response_format": {"type": "json_schema", "json_schema": {"name": stage, "schema": schema, "strict": True}},
        "max_completion_tokens": config.MAX_TOKENS[stage],
    }
    if effort := config.MODEL_EFFORT.get(model):
        request["reasoning_effort"] = effort
    return request


def _call_compat(stage: str, prompt_version: str, model: str, system_parts: list[str], user_text: str,
                 schema: dict, client) -> LLMResult:
    client = client or get_compat_client(provider_of(model)[0])
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(**_compat_request(stage, model, system_parts, user_text, schema))
    except _COMPAT_ERRORS as e:
        raise LLMError(f"{stage} 호출 실패: {type(e).__name__}: {e}") from e
    latency_ms = round((time.perf_counter() - started) * 1000)

    choice = response.choices[0]
    refusal = getattr(choice.message, "refusal", None)
    usage = response.usage
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) or 0
    tokens = {
        "input_tokens": (usage.prompt_tokens or 0) - cached,
        "cache_write_tokens": 0,
        "cache_read_tokens": cached,
        "output_tokens": usage.completion_tokens or 0,
    }
    return LLMResult(
        stage=stage, model=model, prompt_version=prompt_version,
        text=None if refusal else choice.message.content,
        stop_reason="refusal" if refusal else choice.finish_reason, latency_ms=latency_ms,
        cost_usd=cost_usd(model, **tokens), **tokens,
    )


def call(stage: str, prompt_version: str, system_parts: list[str], user_text: str, schema: dict,
         *, model: str | None = None, client=None) -> LLMResult:
    """system_parts는 바뀌지 않는 것부터 순서대로(정책 → 근거). user_text에는 질문만 넣는다."""
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 stage: {stage!r}")
    model = model or config.DEFAULT_MODEL
    if model not in config.PRICES_PER_MTOK:
        raise ValueError(f"단가가 없는 모델: {model!r} (config.PRICES_PER_MTOK)")
    if provider_of(model)[0] != "anthropic":
        return _call_compat(stage, prompt_version, model, system_parts, user_text, schema, client)
    client = client or get_client()
    started = time.perf_counter()
    try:
        response = client.messages.create(**_request(stage, model, system_parts, user_text, schema))
    except anthropic.APIError as e:
        raise LLMError(f"{stage} 호출 실패: {type(e).__name__}: {e}") from e
    except TypeError as e:
        # 인증 정보가 없으면 SDK가 요청 시점에 TypeError를 낸다. 다른 TypeError는 코드 오류이므로 그대로 둔다.
        if "authentication" not in str(e).lower():
            raise
        raise LLMError(f"{stage} 호출 실패: 인증 정보 없음 (ANTHROPIC_API_KEY 확인)") from e
    latency_ms = round((time.perf_counter() - started) * 1000)

    usage = response.usage
    tokens = {
        "input_tokens": usage.input_tokens or 0,
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
        "output_tokens": usage.output_tokens or 0,
    }
    return LLMResult(
        stage=stage, model=model, prompt_version=prompt_version,
        text=next((b.text for b in response.content if b.type == "text"), None),
        stop_reason=response.stop_reason, latency_ms=latency_ms,
        cost_usd=cost_usd(model, **tokens), **tokens,
    )


def record_call(conn: sqlite3.Connection, turn_id: int | None, result: LLMResult) -> int:
    """llm_calls 1행 (PoC2-13)."""
    with conn:
        cur = conn.execute(
            "INSERT INTO llm_calls (turn_id, stage, model, prompt_version, input_tokens, cached_tokens,"
            " cache_write_tokens, output_tokens, stop_reason, latency_ms, cost_usd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (turn_id, result.stage, result.model, result.prompt_version, result.input_tokens,
             result.cache_read_tokens, result.cache_write_tokens, result.output_tokens,
             result.stop_reason, result.latency_ms, result.cost_usd),
        )
    return cur.lastrowid
