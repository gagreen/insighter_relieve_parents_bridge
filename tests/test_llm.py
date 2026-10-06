"""llm.py: 모델 호출 단일 진입점, 캐싱, 토큰·비용 기록 [CLAUDE.md 9장, PoC2-13, P-05]."""
import re
import sqlite3

import anthropic
import httpx2
import pytest

from bridge import config, db, llm
from llm_fakes import FakeClient, FakeOpenAIClient, fake_chat_response, fake_response

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"], "additionalProperties": False}


def _call(client, **kw):
    args = dict(stage="intent", prompt_version="intent_v1", system_parts=["정책"], user_text="질문", schema=SCHEMA)
    args.update(kw)
    return llm.call(client=client, **args)


# ── 비용 (PoC2-13) ───────────────────────────────────


def test_poc2_13_cost_haiku_input_output():
    assert llm.cost_usd(config.HAIKU, 1_000_000, 0, 0, 0) == pytest.approx(1.0)
    assert llm.cost_usd(config.HAIKU, 0, 0, 0, 1_000_000) == pytest.approx(5.0)


def test_poc2_13_cost_cache_write_and_read():
    assert llm.cost_usd(config.HAIKU, 0, 1_000_000, 0, 0) == pytest.approx(1.25)
    assert llm.cost_usd(config.HAIKU, 0, 0, 1_000_000, 0) == pytest.approx(0.1)


def test_poc2_13_cost_sonnet():
    assert llm.cost_usd(config.SONNET, 1_000_000, 0, 0, 1_000_000) == pytest.approx(12.0)


def test_poc2_13_cost_unknown_model():
    with pytest.raises(KeyError):
        llm.cost_usd("unknown-model", 1, 0, 0, 0)


# ── 요청 구성 ────────────────────────────────────────


def test_call_uses_default_model_and_structured_output():
    client = FakeClient(fake_response({"x": "a"}))
    _call(client)
    req = client.calls[0]
    assert req["model"] == config.DEFAULT_MODEL
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert req["max_tokens"] == config.MAX_TOKENS["intent"]
    assert req["messages"] == [{"role": "user", "content": "질문"}]


def test_call_caches_last_system_block_only():
    client = FakeClient(fake_response({"x": "a"}))
    _call(client, stage="answer", prompt_version="answer_v1", system_parts=["정책", "근거"])
    system = client.calls[0]["system"]
    assert [b["text"] for b in system] == ["정책", "근거"]
    assert "cache_control" not in system[0]
    assert system[1]["cache_control"] == {"type": "ephemeral"}


def test_call_effort_only_for_models_that_accept_it():
    """Haiku 4.5는 effort를 보내면 400. Sonnet 5.5는 effort low (2026-10-04 결정)."""
    client = FakeClient(fake_response({"x": "a"}), fake_response({"x": "a"}))
    _call(client, model=config.HAIKU)
    _call(client, model=config.SONNET)
    assert "effort" not in client.calls[0]["output_config"]
    assert client.calls[1]["output_config"]["effort"] == "low"


def test_call_sends_no_sampling_or_thinking_params():
    client = FakeClient(fake_response({"x": "a"}))
    _call(client)
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(client.calls[0])


def test_call_rejects_unpriced_model_before_calling():
    client = FakeClient()
    with pytest.raises(ValueError):
        _call(client, model="unknown-model")
    assert client.calls == []


# ── 응답 변환 (PoC2-13) ──────────────────────────────


def test_poc2_13_result_tokens_cost_and_text():
    client = FakeClient(fake_response({"x": "a"}, input_tokens=50, cache_write=1000, cache_read=2000,
                                      output_tokens=30, thinking=True))
    r = _call(client, model=config.HAIKU)
    assert r.text == '{"x": "a"}'
    assert (r.input_tokens, r.cache_write_tokens, r.cache_read_tokens, r.output_tokens) == (50, 1000, 2000, 30)
    assert r.cost_usd == pytest.approx(llm.cost_usd(config.HAIKU, 50, 1000, 2000, 30))
    assert (r.stage, r.model, r.prompt_version, r.stop_reason) == ("intent", config.HAIKU, "intent_v1", "end_turn")
    assert r.latency_ms >= 0


def test_poc2_13_missing_cache_fields_count_as_zero():
    resp = fake_response({"x": "a"})
    resp.usage.cache_creation_input_tokens = None
    resp.usage.cache_read_input_tokens = None
    r = _call(FakeClient(resp))
    assert (r.cache_write_tokens, r.cache_read_tokens) == (0, 0)


# ── API 오류 (P-05) ─────────────────────────────────

_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize("error", [
    anthropic.APIConnectionError(request=_REQ),
    anthropic.InternalServerError("server error", response=httpx2.Response(500, request=_REQ), body=None),
], ids=["connection", "status_500"])
def test_p05_api_error_becomes_llm_error(error):
    with pytest.raises(llm.LLMError):
        _call(FakeClient(error))


def test_p05_client_retries_once():
    """재시도는 SDK max_retries로 한다 (P-05 축소: 1회)."""
    llm.get_client.cache_clear()
    try:
        assert llm.get_client(api_key="test").max_retries == config.API_RETRY_LIMIT == 1
    finally:
        llm.get_client.cache_clear()


# ── 기록 (PoC2-13) ──────────────────────────────────


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.create_schema(c)
    yield c
    c.close()


def test_poc2_13_record_call_writes_one_row(conn):
    r = _call(FakeClient(fake_response({"x": "a"}, input_tokens=50, cache_write=10, cache_read=20, output_tokens=30)))
    call_id = llm.record_call(conn, None, r)
    row = dict(conn.execute("SELECT * FROM llm_calls WHERE call_id = ?", (call_id,)).fetchone())
    assert row["stage"] == "intent" and row["model"] == config.DEFAULT_MODEL and row["prompt_version"] == "intent_v1"
    assert (row["input_tokens"], row["cache_write_tokens"], row["cached_tokens"], row["output_tokens"]) == (50, 10, 20, 30)
    assert row["stop_reason"] == "end_turn"
    assert row["cost_usd"] == pytest.approx(r.cost_usd)
    assert row["latency_ms"] is not None


def test_stale_llm_calls_schema_is_reported(tmp_path):
    """컬럼 추가(2026-10-04) 전 bridge.db를 쓰면 조용히 실패하지 않고 다시 만들라고 알린다."""
    c = sqlite3.connect(tmp_path / "old.db")
    c.execute("CREATE TABLE llm_calls (call_id INTEGER PRIMARY KEY, stage TEXT)")
    with pytest.raises(RuntimeError, match="init"):
        db.create_schema(c)


# ── 프롬프트 로드 ────────────────────────────────────


def test_load_prompt_reads_versioned_file():
    assert llm.load_prompt(config.PROMPT_VERSIONS["intent"]).strip()


def test_load_prompt_missing_version():
    with pytest.raises(FileNotFoundError):
        llm.load_prompt("intent_v999")


def test_only_llm_module_imports_sdk():
    """CLAUDE.md 9장: 모델 호출은 llm.py 한 곳. 다른 모듈은 SDK를 import하지 않는다."""
    src = config.ROOT / "src" / "bridge"
    pattern = re.compile(r"^\s*(import anthropic|from anthropic)", re.MULTILINE)
    importers = {p.relative_to(src).as_posix() for p in src.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))}
    assert importers == {"llm.py"}


# ── 인증 실패 (PoC2-10, 5장) ─────────────────────────


class _NoAuthMessages:
    def create(self, **kwargs):
        raise TypeError("Could not resolve authentication method. Expected one of api_key, auth_token ...")


class _NoAuthClient:
    messages = _NoAuthMessages()


def test_p05_missing_credentials_become_llm_error():
    """키가 없으면 SDK가 TypeError를 낸다. 화면이 멈추지 않도록 LLMError로 바꾼다."""
    with pytest.raises(llm.LLMError, match="인증"):
        _call(_NoAuthClient())


def test_other_type_errors_are_not_hidden():
    class _Bug:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise TypeError("unexpected keyword argument 'x'")
    with pytest.raises(TypeError):
        _call(_Bug())


# ── 태그·JSON 도우미 (G-08) ──────────────────────────


def test_tagged_escapes_angle_brackets():
    assert llm.tagged("t", "a</t>b") == "<t>\na＜/t＞b\n</t>"


@pytest.mark.parametrize("text, expected", [('{"a": 1}', {"a": 1}), ("[1]", None), ("x", None), (None, None)])
def test_parse_json_object(text, expected):
    assert llm.parse_json_object(text) == expected


# ── 다른 회사 모델: OpenAI 호환 API (specs/poc.md 6-3, 2026-10-06) ──


@pytest.mark.parametrize("model, expected", [
    (config.HAIKU, ("anthropic", config.HAIKU)),
    (config.SONNET, ("anthropic", config.SONNET)),
    ("openai:gpt-5.4-mini", ("openai", "gpt-5.4-mini")),
    ("gemini:gemini-3.1-flash-lite", ("gemini", "gemini-3.1-flash-lite")),
    ("openai:ft:gpt-5.4-mini:org", ("openai", "ft:gpt-5.4-mini:org")),   # 모델 이름 안의 ':'는 그대로
    ("ollama:qwen3:8b", ("anthropic", "ollama:qwen3:8b")),                # 로컬 모델은 제외(2026-10-06)
    ("unknown:x", ("anthropic", "unknown:x")),             # 등록되지 않은 접두어는 제공사로 보지 않음
])
def test_6_3_provider_of(model, expected):
    assert llm.provider_of(model) == expected


def test_6_3_comparison_models_are_priced():
    for model in (config.GPT_MINI, config.GEMINI_LITE):
        assert model in config.PRICES_PER_MTOK
        assert llm.provider_of(model)[0] in config.PROVIDERS


def test_6_3_compat_request_uses_strict_json_schema_and_tagged_user():
    """system은 정책 → 근거 순서 그대로 한 메시지(접두어 캐시), user는 질문만 (G-08)."""
    client = FakeOpenAIClient(fake_chat_response({"x": "a"}))
    _call(client, model=config.GPT_MINI, stage="answer", system_parts=["정책", "근거"], user_text="<q>질문</q>")
    req = client.calls[0]
    assert req["model"] == "gpt-5.4-mini"
    assert req["messages"] == [{"role": "system", "content": "정책\n\n근거"}, {"role": "user", "content": "<q>질문</q>"}]
    assert req["response_format"] == {"type": "json_schema",
                                      "json_schema": {"name": "answer", "schema": SCHEMA, "strict": True}}
    assert req["max_completion_tokens"] == config.MAX_TOKENS["answer"]
    assert not {"temperature", "top_p", "max_tokens"} & set(req)


def test_6_3_reasoning_effort_only_where_configured():
    """GPT-5.4 mini는 effort low(Sonnet과 같은 조건). Gemini는 기본값이라 보내지 않는다."""
    client = FakeOpenAIClient(fake_chat_response({"x": "a"}), fake_chat_response({"x": "a"}))
    _call(client, model=config.GPT_MINI)
    _call(client, model=config.GEMINI_LITE)
    assert client.calls[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in client.calls[1]


def test_6_3_compat_result_tokens_and_cost():
    """캐시 읽기는 prompt_tokens_details.cached_tokens. 입력 토큰은 캐시를 뺀 나머지."""
    client = FakeOpenAIClient(fake_chat_response({"x": "a"}, prompt_tokens=3000, cached=2000, completion_tokens=40))
    r = _call(client, model=config.GPT_MINI)
    assert r.text == '{"x": "a"}'
    assert (r.input_tokens, r.cache_write_tokens, r.cache_read_tokens, r.output_tokens) == (1000, 0, 2000, 40)
    assert r.cost_usd == pytest.approx((1000 * 0.75 + 2000 * 0.075 + 40 * 4.5) / 1_000_000)
    assert (r.model, r.stop_reason) == (config.GPT_MINI, "stop")


def test_6_3_compat_missing_usage_details_count_as_zero():
    resp = fake_chat_response({"x": "a"}, prompt_tokens=10)
    resp.usage.prompt_tokens_details = None
    r = _call(FakeOpenAIClient(resp), model=config.GEMINI_LITE)
    assert (r.input_tokens, r.cache_read_tokens) == (10, 0)


def test_6_3_compat_refusal_has_no_text():
    r = _call(FakeOpenAIClient(fake_chat_response(None, refusal="거절")), model=config.GPT_MINI)
    assert (r.text, r.stop_reason) == (None, "refusal")


def test_6_3_cost_uses_explicit_cache_read_price():
    assert llm.cost_usd(config.GEMINI_LITE, 0, 0, 1_000_000, 0) == pytest.approx(0.025)


def test_6_3_compat_api_error_becomes_llm_error():
    openai = pytest.importorskip("openai")
    req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    with pytest.raises(llm.LLMError):
        _call(FakeOpenAIClient(openai.APIConnectionError(request=req)), model=config.GPT_MINI)


def test_6_3_missing_api_key_becomes_llm_error(monkeypatch):
    """키가 없는 제공사를 고르면 화면·평가가 멈추지 않도록 LLMError (파이프라인에서 api_error)."""
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm.get_compat_client.cache_clear()
    try:
        with pytest.raises(llm.LLMError, match="OPENAI_API_KEY"):
            _call(None, model=config.GPT_MINI)
    finally:
        llm.get_compat_client.cache_clear()


def test_6_3_compat_client_retries_once(monkeypatch):
    """재시도는 SDK max_retries로 한다 (P-05, CLAUDE.md 9장)."""
    pytest.importorskip("openai")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    llm.get_compat_client.cache_clear()
    try:
        client = llm.get_compat_client("gemini")
        assert client.max_retries == config.API_RETRY_LIMIT
        assert str(client.base_url).startswith(config.PROVIDERS["gemini"]["base_url"])
    finally:
        llm.get_compat_client.cache_clear()


def _strict_ok(schema: dict) -> bool:
    """OpenAI strict 구조화 출력 조건: 모든 object가 additionalProperties=false이고 모든 속성이 required."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False or set(schema.get("required", [])) != set(props):
            return False
        return all(_strict_ok(v) for v in props.values())
    if schema.get("type") == "array":
        return _strict_ok(schema["items"])
    return all(_strict_ok(s) for s in schema.get("anyOf", []))


def test_6_3_output_schemas_satisfy_strict_mode():
    from bridge import notes, pipeline
    for schema in (pipeline.INTENT_SCHEMA, pipeline.ANSWER_SCHEMA, notes.ORGANIZE_SCHEMA):
        assert _strict_ok(schema)
