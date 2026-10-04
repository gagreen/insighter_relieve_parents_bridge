"""SQLite 스키마 생성·샘플 적재 (CLAUDE.md 8-3, specs/poc.md 2-4).

사용법: python -m bridge.db init [DB 경로]
"""
import json
import sqlite3
import sys
from pathlib import Path

from bridge import config
from bridge.ingest.validate import validate_payload

SCHEMA = """
CREATE TABLE IF NOT EXISTS assessment_types (
    code           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    respondent     TEXT,
    schema_version INTEGER NOT NULL,
    definition     TEXT NOT NULL              -- JSON (specs/poc.md 2-2)
);

CREATE TABLE IF NOT EXISTS assessment_results (
    result_id       TEXT PRIMARY KEY,
    child_id        TEXT NOT NULL,            -- 가명
    assessment_code TEXT NOT NULL REFERENCES assessment_types(code),
    administered_at TEXT,
    schema_version  INTEGER NOT NULL,
    payload         TEXT NOT NULL             -- JSON (CLAUDE.md 8-1)
);

-- 식별 정보. 마스킹(PoC2-02)만 읽고 프롬프트·화면 요약에 넣지 않는다 (G-09)
CREATE TABLE IF NOT EXISTS subjects (
    child_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    sex          TEXT,
    birth_date   TEXT,
    school_level TEXT,
    grade        TEXT
);

CREATE TABLE IF NOT EXISTS qa_turns (
    turn_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id          TEXT NOT NULL,
    question_masked   TEXT NOT NULL,
    intent            TEXT,
    intent_confidence REAL,
    route             TEXT,                   -- crisis/safe/redirect/answer/api_error (2026-10-04 추가)
    answer            TEXT,
    evidence_refs     TEXT,                   -- JSON 배열
    guard_result      TEXT CHECK (guard_result IN ('pass', 'regen', 'fallback')),
    crisis_flag       INTEGER NOT NULL DEFAULT 0,
    saved_to_note     INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS note_items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id        TEXT NOT NULL,
    source_turn_id  INTEGER REFERENCES qa_turns(turn_id),
    text            TEXT NOT NULL,            -- 마스킹된 문장 (G-09)
    type            TEXT,
    related_refs    TEXT,                     -- JSON 배열
    parent_edited   INTEGER NOT NULL DEFAULT 0,
    parent_approved INTEGER NOT NULL DEFAULT 0, -- PoC: 승인 흐름 없음 (G-10)
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id        INTEGER REFERENCES qa_turns(turn_id),
    stage          TEXT NOT NULL CHECK (stage IN ('intent', 'answer', 'organize')),
    model          TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_tokens   INTEGER,                  -- 캐시를 거치지 않은 입력
    cached_tokens  INTEGER,                  -- 캐시 읽기
    cache_write_tokens INTEGER,              -- 캐시 쓰기 (2026-10-04 추가)
    output_tokens  INTEGER,
    stop_reason    TEXT,                     -- end_turn / max_tokens / refusal ... (2026-10-04 추가)
    latency_ms     INTEGER,
    cost_usd       REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# 나중에 추가한 컬럼. CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 더하지 않으므로 확인한다.
ADDED_COLUMNS = {"llm_calls": ("cache_write_tokens", "stop_reason"), "qa_turns": ("route",)}


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if missing := [c for c in columns if c not in existing]:
            raise RuntimeError(f"DB 스키마가 오래되었습니다({table}에 {missing} 없음). "
                               "DB 파일을 지우고 `python -m bridge.db init`을 다시 실행하세요.")


def load_samples(
    conn: sqlite3.Connection,
    types_dir: Path = config.ASSESSMENT_TYPES_DIR,
    results_dir: Path = config.RESULTS_DIR,
) -> list[tuple[str, list[str]]]:
    """검사 정의와 결과를 적재하고, 스키마 검증에 실패해 저장하지 않은 (result_id, 오류)를 돌려준다.

    subject(식별 정보)는 subjects 테이블에만 넣고, sample_meta(테스트 기대값)는 적재하지 않는다(8-4, G-09).
    """
    with conn:
        for path in sorted(types_dir.glob("*.json")):
            t = json.loads(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO assessment_types VALUES (?, ?, ?, ?, ?)",
                (t["code"], t["name"], t.get("respondent"), t["schema_version"],
                 json.dumps(t["definition"], ensure_ascii=False)),
            )

        rejected = []
        for path in sorted(results_dir.glob("*.json")):
            r = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_payload(r["payload"], r["assessment_code"])
            if errors:
                rejected.append((r["result_id"], errors))
                continue
            conn.execute(
                "INSERT OR REPLACE INTO assessment_results VALUES (?, ?, ?, ?, ?, ?)",
                (r["result_id"], r["child_id"], r["assessment_code"], r["administered_at"],
                 r["schema_version"], json.dumps(r["payload"], ensure_ascii=False)),
            )
            s = r["subject"]
            conn.execute(
                "INSERT OR REPLACE INTO subjects VALUES (?, ?, ?, ?, ?, ?)",
                (r["child_id"], s["name"], s.get("sex"), s.get("birth_date"), s.get("school_level"), s.get("grade")),
            )
    return rejected


def init(path: Path | str | None = None) -> list[tuple[str, list[str]]]:
    conn = connect(path)
    try:
        create_schema(conn)
        return load_samples(conn)
    finally:
        conn.close()


def get_definition(conn: sqlite3.Connection, code: str) -> dict:
    row = conn.execute("SELECT definition FROM assessment_types WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise KeyError(f"검사 정의 없음: {code}")
    return json.loads(row["definition"])


def get_payload(conn: sqlite3.Connection, result_id: str) -> dict:
    row = conn.execute("SELECT payload FROM assessment_results WHERE result_id = ?", (result_id,)).fetchone()
    if row is None:
        raise KeyError(f"검사 결과 없음: {result_id}")
    return json.loads(row["payload"])


def get_result(conn: sqlite3.Connection, result_id: str) -> dict:
    """검사 결과 1건(식별 정보 없음): result_id, child_id(가명), assessment_code, payload."""
    row = conn.execute("SELECT result_id, child_id, assessment_code, payload FROM assessment_results"
                       " WHERE result_id = ?", (result_id,)).fetchone()
    if row is None:
        raise KeyError(f"검사 결과 없음: {result_id}")
    return {**dict(row), "payload": json.loads(row["payload"])}


def get_subject(conn: sqlite3.Connection, child_id: str) -> dict:
    """식별 정보 조회. 마스킹 모듈 전용 (G-09)."""
    row = conn.execute("SELECT * FROM subjects WHERE child_id = ?", (child_id,)).fetchone()
    if row is None:
        raise KeyError(f"식별 정보 없음: {child_id}")
    return dict(row)


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "init":
        print("사용법: python -m bridge.db init [DB 경로]", file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) > 1 else config.DB_PATH
    rejected = init(path)
    conn = connect(path)
    n_types = conn.execute("SELECT COUNT(*) FROM assessment_types").fetchone()[0]
    n_results = conn.execute("SELECT COUNT(*) FROM assessment_results").fetchone()[0]
    conn.close()
    print(f"{path}: 검사 정의 {n_types}건, 검사 결과 {n_results}건 적재")
    for result_id, errors in rejected:
        print(f"  스키마 검증 실패, 저장 안 함: {result_id}", file=sys.stderr)
        for e in errors:
            print(f"    - {e}", file=sys.stderr)
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
