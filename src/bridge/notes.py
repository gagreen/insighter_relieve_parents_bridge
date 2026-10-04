"""질문 노트 [G-09, G-10].

저장 문장은 마스킹된 원래 질문이다(specs/poc.md PoC2-05). PoC에는 승인 흐름이 없고 parent_approved 컬럼만 둔다(G-10).
질문 정리(PoC2-11)는 다음 작업에서 추가한다.
"""
import json
import sqlite3


def save_note(conn: sqlite3.Connection, child_id: str, turn_id: int, text: str, type_: str,
              related_refs: list[str]) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO note_items (child_id, source_turn_id, text, type, related_refs) VALUES (?, ?, ?, ?, ?)",
            (child_id, turn_id, text, type_, json.dumps(related_refs, ensure_ascii=False)),
        )
    return cur.lastrowid


def list_notes(conn: sqlite3.Connection, child_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM note_items WHERE child_id = ? ORDER BY item_id", (child_id,)).fetchall()
    return [{**dict(r), "related_refs": json.loads(r["related_refs"] or "[]")} for r in rows]
