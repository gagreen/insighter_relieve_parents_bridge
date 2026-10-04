"""specs/poc.md 2-4 적재 [CLAUDE.md 8-1, 8-3]."""
import json
import shutil

from bridge import config, db

TABLE_COLUMNS = {
    "assessment_types": {"code", "name", "respondent", "schema_version", "definition"},
    "assessment_results": {"result_id", "child_id", "assessment_code", "administered_at", "schema_version", "payload"},
    "subjects": {"child_id", "name", "sex", "birth_date", "school_level", "grade"},
    "qa_turns": {"turn_id", "child_id", "question_masked", "intent", "intent_confidence", "route", "answer",
                 "evidence_refs", "guard_result", "crisis_flag", "saved_to_note"},
    "note_items": {"item_id", "child_id", "source_turn_id", "text", "type", "related_refs",
                   "parent_edited", "parent_approved"},
    "llm_calls": {"call_id", "turn_id", "stage", "model", "prompt_version", "input_tokens", "cached_tokens", "cache_write_tokens", "stop_reason",
                  "output_tokens", "latency_ms", "cost_usd"},
}


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_2_4_init_creates_tables_with_core_columns(loaded_db):
    for table, cols in TABLE_COLUMNS.items():
        assert cols <= _columns(loaded_db, table), table


def test_2_4_init_loads_definition_and_all_results(loaded_db):
    assert loaded_db.execute("SELECT COUNT(*) FROM assessment_types").fetchone()[0] == 1
    assert loaded_db.execute("SELECT COUNT(*) FROM assessment_results").fetchone()[0] == 100
    definition = db.get_definition(loaded_db, "KCBCL_4_17")
    assert definition["groups"]["composite"]["clinical_min"] == 63
    assert definition["groups"]["syndrome"]["clinical_min"] == 70


def test_2_4_payload_round_trip_matches_file(loaded_db):
    src = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
    assert db.get_payload(loaded_db, src["result_id"]) == src["payload"]


def test_2_4_subject_loaded_only_into_subjects(loaded_db):
    """G-09: 식별 정보(subject)는 subjects 테이블에만 있다."""
    src = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
    assert db.get_subject(loaded_db, src["child_id"]) == src["subject"]
    assert loaded_db.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 100

    other_tables = "\n".join(
        line for line in loaded_db.iterdump() if '"subjects"' not in line and "subjects " not in line
    )
    assert src["subject"]["name"] not in other_tables
    assert src["subject"]["birth_date"] not in other_tables


def test_2_4_sample_meta_not_stored(loaded_db):
    dump = "\n".join(loaded_db.iterdump())
    assert "sample_meta" not in dump and "severity_tier" not in dump


def test_2_4_reinit_does_not_duplicate(tmp_path):
    path = tmp_path / "bridge.db"
    db.init(path)
    db.init(path)
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM assessment_results").fetchone()[0] == 100
    assert conn.execute("SELECT COUNT(*) FROM assessment_types").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 100


def test_2_4_schema_invalid_payload_not_stored(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    shutil.copy(config.BASE_SAMPLE_FILE, results_dir / "035.json")
    bad = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
    bad["result_id"] = "R-BAD"
    bad["child_id"] = bad["subject"]["child_id"] = "C-BAD"
    bad["payload"]["scores"][0]["range"] = "정상"  # enum 위반
    (results_dir / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")

    conn = db.connect(tmp_path / "bridge.db")
    db.create_schema(conn)
    rejected = db.load_samples(conn, results_dir=results_dir)

    assert [r for r, _ in rejected] == ["R-BAD"]
    ids = [r[0] for r in conn.execute("SELECT result_id FROM assessment_results")]
    assert ids == ["R-KCBCL_4_17-035"]
    # 저장하지 않은 결과의 식별 정보도 남기지 않는다
    base_child_id = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))["child_id"]
    assert [r[0] for r in conn.execute("SELECT child_id FROM subjects")] == [base_child_id]


def test_2_4_1_init_also_loads_private_results(tmp_path, monkeypatch):
    """spec 2-4-1: data/private/kcbcl_results/가 있으면 함께 적재 (subject는 subjects 테이블에만)."""
    private = tmp_path / "private"
    private.mkdir()
    r = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
    r.update(result_id="R-PRIVATE-TEST", child_id="C-PRIVATE")
    r["subject"] = {**r["subject"], "child_id": "C-PRIVATE", "name": "홍길동"}
    (private / "report.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "PRIVATE_RESULTS_DIR", private)
    path = tmp_path / "t.db"
    assert db.init(path) == []
    conn = db.connect(path)
    assert db.get_result(conn, "R-PRIVATE-TEST")["child_id"] == "C-PRIVATE"
    assert db.get_subject(conn, "C-PRIVATE")["name"] == "홍길동"
    assert "홍길동" not in json.dumps(db.get_payload(conn, "R-PRIVATE-TEST"), ensure_ascii=False)
    conn.close()


def test_2_4_1_private_dir_is_git_ignored():
    """CLAUDE.md 11장: 회사 보고서를 옮긴 JSON은 커밋하지 않는다."""
    import subprocess
    out = subprocess.run(["git", "check-ignore", "-q", "data/private/kcbcl_results/report.json"], cwd=config.ROOT)
    assert out.returncode == 0
