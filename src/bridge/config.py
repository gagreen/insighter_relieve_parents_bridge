"""정책 상수(P-xx), 모델 ID, 단가, 경로.

기획안의 가정값은 여기에만 둔다(CLAUDE.md 3장 5항). 판정 기준(G-02)은 여기가 아니라
assessment_types.definition 데이터에 둔다.
"""
import os
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
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

# ── 정책 상수 (CLAUDE.md 6장) ─────────────────────────
# P-01 입력 길이. 가정: 기획안 2-5
MAX_INPUT_CHARS = 1000
# P-03 출력 검증 실패 시 자동 재생성 횟수 (PoC 축소). 가정: 기획안 2-5
AUTO_REGEN_LIMIT = 1
# P-05 API 오류 재시도 횟수 (PoC 축소). 가정: 기획안 2-5
API_RETRY_LIMIT = 1
# 의도 분류 신뢰도 임계값. 미정: 평가셋 1차 실행 후 결정 (specs/poc.md PoC2-04)
INTENT_CONFIDENCE_THRESHOLD: float | None = None
