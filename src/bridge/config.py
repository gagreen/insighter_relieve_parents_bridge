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

# 100만 토큰당 USD. 출처: 기획안 6장, Anthropic 가격표 2026-10-02 조회
PRICES_PER_MTOK = {
    HAIKU: {"input": 1.0, "output": 5.0},
    SONNET: {"input": 2.0, "output": 10.0},
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

# 모델별 effort (CLAUDE.md 9장, 2026-10-04 결정). Haiku 4.5는 effort를 받지 않는다(보내면 400).
# Sonnet 5.5는 adaptive thinking(기본값) + effort low.
MODEL_EFFORT = {SONNET: "low"}
# 단계별 최대 출력 토큰. Sonnet은 thinking 토큰도 여기에 포함된다.
MAX_TOKENS = {"intent": 1024, "answer": 4096, "organize": 4096}

# ── 프롬프트 (CLAUDE.md 7장) ──────────────────────────
# 현재 쓰는 버전. 기존 버전 파일은 고치지 않고 새 버전 파일을 만든 뒤 여기만 바꾼다.
PROMPT_VERSIONS = {"intent": "intent_v1", "answer": "answer_v1"}

# ── 정책 상수 (CLAUDE.md 6장) ─────────────────────────
# P-01 입력 길이. 가정: 기획안 2-5
MAX_INPUT_CHARS = 1000
# P-03 출력 검증 실패 시 자동 재생성 횟수 (PoC 축소). 가정: 기획안 2-5
AUTO_REGEN_LIMIT = 1
# P-05 API 오류 재시도 횟수 (PoC 축소). 가정: 기획안 2-5
API_RETRY_LIMIT = 1
# 의도 분류 신뢰도 임계값. 가정: 평가셋 1차 실행 전 임시값 (specs/poc.md PoC2-04, 2026-10-04)
INTENT_CONFIDENCE_THRESHOLD = 0.7

# 의도 → 처리 경로 (specs/poc.md 2-5). 신뢰도 미달·분류 실패는 safe.
ROUTE_BY_INTENT = {
    "explain": "answer",
    "diagnosis": "safe",
    "parenting": "safe",  # 가정: 기획안 2-7 (양육 방법 추천을 처방으로 보고 제외)
    "crisis": "crisis",
    "out_of_scope": "redirect",
}
UNCLASSIFIED_ROUTE = "safe"
