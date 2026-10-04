"""PoC2-12 상담사 브리프 텍스트 (M3) [G-10, G-11].

코드가 조립한다(LLM은 질문 정리만). 보고서 점수·보호자 의견은 다시 나열하지 않고, 관련 항목은 'id · 이름'만 쓴다.
PoC는 승인 흐름 없이 저장된 노트를 모두 넣는다(G-10 PoC 제외). 위기 표시는 항상 넣는다.

사용법: python -m bridge.brief <result_id> [--db PATH] [--since TURN_ID] [--no-llm]
"""
import argparse
import json
import sqlite3
import sys

from bridge import config, db, notes, pipeline
from bridge.evidence import item_label
from bridge.notes import OrganizeResult

TYPE_LABELS = {"diagnosis": "진단·치료·경과", "parenting": "양육", "understanding": "결과·용어 이해", "other": "기타"}
SOURCE_LABELS = {
    "llm": "AI 정리(검수 전)",
    "regen": "AI 정리(검수 전)",
    "fallback": "자동 정리 실패 — 원래 질문 목록",
    "skipped": "정리하지 않음 — 원래 질문 목록",
}


def answered_turns(conn: sqlite3.Connection, child_id: str, since_turn_id: int | None = None) -> list[dict]:
    """AI가 답한 설명형 질문: route=answer, 출력 검증 통과(pass/regen), 노트 미저장(= 답이 나감)."""
    rows = conn.execute(
        "SELECT turn_id, question_masked, answer, evidence_refs FROM qa_turns"
        " WHERE child_id = ? AND turn_id > ? AND route = 'answer' AND guard_result IN ('pass', 'regen')"
        " AND saved_to_note = 0 ORDER BY turn_id",
        (child_id, since_turn_id or 0),
    ).fetchall()
    return [{**dict(r), "evidence_refs": json.loads(r["evidence_refs"] or "[]")} for r in rows]


def crisis_turns(conn: sqlite3.Connection, child_id: str, since_turn_id: int | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT turn_id, question_masked, created_at FROM qa_turns"
        " WHERE child_id = ? AND turn_id > ? AND crisis_flag = 1 ORDER BY turn_id",
        (child_id, since_turn_id or 0),
    ).fetchall()
    return [dict(r) for r in rows]


def _refs(ctx: pipeline.Context, refs: list[str]) -> str:
    return ", ".join(item_label(ctx.pack.items[r]) if r in ctx.pack.items else r for r in refs)


def build_brief(ctx: pipeline.Context, organized: OrganizeResult, answered: list[dict], crisis: list[dict]) -> str:
    lines = [
        f"[상담 브리프] 검사 결과 {ctx.result_id} · 아동 {ctx.child_id}",
        "보호자가 결과 보고서를 읽은 뒤 남긴 질문입니다. 점수와 보호자 의견은 보고서 원문을 참고하세요.",
        "",
        "① 보호자 질문",
    ]
    if not organized.items:
        lines.append("  (저장된 질문 없음)")
    else:
        lines.append(f"  정리: {SOURCE_LABELS[organized.source]}")
        for type_ in notes.BRIEF_TYPES:
            group = [i for i in organized.items if i.type == type_]
            if not group:
                continue
            lines.append(f"  [{TYPE_LABELS[type_]}]")
            for item in group:
                lines.append(f"  - {item.text}")
                if item.related_refs:
                    lines.append(f"    관련 항목: {_refs(ctx, item.related_refs)}")
                lines.append(f"    원래 질문: turn {', '.join(map(str, item.source_turn_ids))}")

    lines += ["", "② AI가 답한 설명형 질문"]
    if not answered:
        lines.append("  (없음)")
    for t in answered:
        lines += [f"  - Q (turn {t['turn_id']}): {t['question_masked']}", f"    A [AI 생성]: {t['answer']}"]
        if t["evidence_refs"]:
            lines.append(f"    근거: {_refs(ctx, t['evidence_refs'])}")

    lines += ["", "③ 위기 표시"]
    if not crisis:
        lines.append("  (없음)")
    for t in crisis:
        lines.append(f"  - [위기] turn {t['turn_id']} ({t['created_at']}): {t['question_masked']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.brief", description="상담사 브리프 텍스트 출력 (PoC2-12)")
    parser.add_argument("result_id")
    parser.add_argument("--db", default=str(config.DB_PATH))
    parser.add_argument("--since", type=int, default=None, help="이 turn_id 이후 기록만")
    parser.add_argument("--no-llm", action="store_true", help="질문 정리 LLM을 부르지 않고 원래 질문 목록을 쓴다")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    try:
        ctx = pipeline.load_context(conn, args.result_id)
        items = notes.list_notes(conn, ctx.child_id, args.since)
        organized = notes.skipped(items) if args.no_llm else notes.organize_notes(conn, items)
        print(build_brief(ctx, organized, answered_turns(conn, ctx.child_id, args.since),
                          crisis_turns(conn, ctx.child_id, args.since)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
