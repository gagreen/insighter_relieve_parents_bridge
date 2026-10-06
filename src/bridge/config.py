"""정책 상수(P-xx), 모델 ID, 단가, 경로.

기획안의 가정값은 여기에만 둔다(CLAUDE.md 3장 5항). 판정 기준(G-02)은 여기가 아니라
assessment_types.definition 데이터에 둔다.
"""
import os
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> dict[str, str]:
    """`.env`의 KEY=VALUE를 아직 설정되지 않은 환경 변수에만 넣는다(셸 설정이 우선). 표준 라이브러리만 쓴다.

    빈 줄·`#` 주석·형식이 틀린 줄은 건너뛰고, 앞의 `export `와 값 양끝의 같은 따옴표를 뗀다.
    값 안의 `=`, `:`, `#`은 그대로 둔다. 빈 값은 넣지 않는다. 실제로 넣은 항목을 돌려준다.
    """
    if not path.exists():
        return {}
    applied = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key or not value or key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


# 아래 os.environ 조회(LLM_MODEL, BRIDGE_DB_PATH)와 SDK의 ANTHROPIC_* 조회보다 먼저 읽는다.
load_env_file(ROOT / ".env")

DATA_DIR = ROOT / "data"
RESULTS_DIR = DATA_DIR / "kcbcl_results"
# 회사 제공 보고서를 옮긴 결과(커밋 안 함, specs/poc.md 2-4-1). 있으면 함께 적재한다
PRIVATE_RESULTS_DIR = DATA_DIR / "private" / "kcbcl_results"
ASSESSMENT_TYPES_DIR = DATA_DIR / "assessment_types"
SCHEMAS_DIR = ROOT / "schemas"
CONTENT_DIR = ROOT / "content"
PROMPTS_DIR = ROOT / "prompts"
EVAL_DIR = ROOT / "eval"
DB_PATH = Path(os.environ.get("BRIDGE_DB_PATH", ROOT / "bridge.db"))

# 데모·평가 기준 샘플 (specs/poc.md 2-3)
BASE_SAMPLE_FILE = RESULTS_DIR / "035.json"

# ── 모델 (CLAUDE.md 9장) ──────────────────────────────
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"
DEFAULT_MODEL = os.environ.get("LLM_MODEL", HAIKU)

# 다른 회사 비교 모델 (specs/poc.md 6-3, 2026-10-06). '<제공사>:<모델>' 형식, 제공사는 PROVIDERS
GPT_MINI = "openai:gpt-5.4-mini"
GEMINI_LITE = "gemini:gemini-3.1-flash-lite"

# OpenAI 호환 API 제공사. 로컬 모델(Ollama)은 단가를 계산할 수 없어 제외 (2026-10-06)
PROVIDERS = {
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "key_env": "GEMINI_API_KEY"},
}

# 100만 토큰당 USD. 출처: 기획안 6장, Anthropic 가격표 2026-10-02 조회.
# 다른 회사: 공식 문서 2026-10-06 조회 (OpenAI 모델 페이지, Gemini API 가격표 Standard). cache_read가 없으면 입력 × 0.1.
PRICES_PER_MTOK = {
    HAIKU: {"input": 1.0, "output": 5.0},
    SONNET: {"input": 2.0, "output": 10.0},
    GPT_MINI: {"input": 0.75, "output": 4.5, "cache_read": 0.075},
    GEMINI_LITE: {"input": 0.25, "output": 1.5, "cache_read": 0.025},   # 무료 등급으로 실행해도 유료 단가로 환산 기록
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1
# 무료 등급으로 실행하는 모델. 입력이 제공사 제품 개선에 쓰일 수 있어 합성 샘플만 보낸다 (specs/poc.md 6-3)
FREE_TIER_MODELS = {GEMINI_LITE}

# 모델별 effort (CLAUDE.md 9장, 2026-10-04 결정). Haiku 4.5는 effort를 받지 않는다(보내면 400).
# Sonnet 5.5는 adaptive thinking(기본값) + effort low. GPT-5.4 mini는 reasoning_effort low(기본 none, Sonnet과 맞춤, 2026-10-06).
MODEL_EFFORT = {SONNET: "low", GPT_MINI: "low"}
# 단계별 최대 출력 토큰. Sonnet은 thinking 토큰도 여기에 포함된다.
MAX_TOKENS = {"intent": 1024, "answer": 4096, "organize": 4096}

# ── 프롬프트 (CLAUDE.md 7장) ──────────────────────────
# 현재 쓰는 버전. 기존 버전 파일은 고치지 않고 새 버전 파일을 만든 뒤 여기만 바꾼다.
# answer_v3 (2026-10-06): 답 손실 개선 — 예시 숫자·차이 계산 금지, gap 인용, id 복사, 재생성 사유 (specs/poc.md PoC2-07)
# intent_v3 (2026-10-06): 감정 관용어는 위기가 아님, consult_prep 추가 (specs/poc.md PoC2-03·04)
PROMPT_VERSIONS = {"intent": "intent_v3", "answer": "answer_v3", "organize": "organize_v1"}

# ── 정책 상수 (CLAUDE.md 6장) ─────────────────────────
# P-01 입력 길이. 가정: 기획안 2-5
MAX_INPUT_CHARS = 1000
# P-03 출력 검증 실패 시 자동 재생성 횟수 (PoC 축소). 가정: 기획안 2-5
AUTO_REGEN_LIMIT = 1
# P-05 API 오류 재시도 횟수 (PoC 축소). 가정: 기획안 2-5
API_RETRY_LIMIT = 1
# 의도 분류 신뢰도 임계값. 2026-10-06 확정 (specs/poc.md PoC2-04): intent_v2에서 Haiku·GPT·Gemini 최소 0.84, 오분류 0건.
# 미달은 안전 쪽(safe)으로 가므로 보수적으로 둔다.
INTENT_CONFIDENCE_THRESHOLD = 0.7
# 안전 응답에 사실 문장으로 넣는 척도 수 상한. 설계값: 응답이 길어져 읽히지 않는 것을 막음 (specs/poc.md PoC2-05, 2026-10-05)
SAFE_MAX_SCALES = 3
# 낱말 뜻 질문에 답하는 용어 수 상한. 설계값 (specs/poc.md PoC2-14, 2026-10-06)
GLOSSARY_QA_MAX_TERMS = 2

# 의도 → 처리 경로 (specs/poc.md 2-5). 신뢰도 미달·분류 실패는 safe.
ROUTE_BY_INTENT = {
    "explain": "answer",
    "diagnosis": "safe",
    "parenting": "safe",  # 양육 방법 추천은 처방에 해당 (2026-10-05 사용자 확정, 기획안 2-7)
    "crisis": "crisis",
    "out_of_scope": "redirect",
    "consult_prep": "prep",   # 상담 준비 안내 (specs/poc.md PoC2-15, 2026-10-06)
}
UNCLASSIFIED_ROUTE = "safe"
