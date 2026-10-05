"""PoC2-11 질문 정리 [G-01, G-03, G-06, G-09]. LLM은 모킹한다."""
import json

import anthropic
import httpx2
import pytest

from bridge import config, db, notes
from llm_fakes import FakeClient, fake_response

CHILD = "C-T"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.create_schema(c)
    yield c
    c.close()


def _note(conn, text, type_="diagnosis", refs=()):
    with conn:
        tid = conn.execute("INSERT INTO qa_turns (child_id, question_masked, route) VALUES (?, ?, 'safe')",
                           (CHILD, text)).lastrowid
    notes.save_note(conn, CHILD, tid, text, type_, list(refs))
    return tid


@pytest.fixture
def three(conn):
    _note(conn, "ADHD인가요?", "diagnosis", ["III.attention"])
    _note(conn, "ADHD 검사를 더 받아야 하나요?", "diagnosis", ["III.attention", "VI.rec1"])
    _note(conn, "숙제할 때 집중을 못 하는데 집에서 어떻게 해요?", "parenting", [])
    return notes.list_notes(conn, CHILD)


def _ids(items):
    return [n["item_id"] for n in items]


def _good(items):
    a, b, c = _ids(items)
    return {"items": [
        {"text": "ADHD인지, 검사를 더 받아야 하는지 궁금해요.", "type": "diagnosis", "source_item_ids": [a, b]},
        {"text": "숙제할 때 집중을 못 하는데 집에서 어떻게 해야 하나요?", "type": "parenting", "source_item_ids": [c]},
    ]}


def test_poc2_11_no_notes_no_llm_call(conn):
    client = FakeClient()
    r = notes.organize_notes(conn, [], client=client)
    assert (r.items, r.source, client.calls) == ([], "empty", [])


def test_poc2_11_merge_keeps_links(conn, three):
    r = notes.organize_notes(conn, three, client=FakeClient(fake_response(_good(three))))
    assert r.source == "llm" and len(r.items) == 2
    merged = r.items[0]
    assert merged.source_item_ids == _ids(three)[:2]
    assert merged.source_turn_ids == [n["source_turn_id"] for n in three[:2]]   # 원래 질문 연결 유지
    assert merged.related_refs == ["III.attention", "VI.rec1"]                  # 코드가 합침


def test_poc2_11_call_is_recorded_without_turn(conn, three):
    notes.organize_notes(conn, three, client=FakeClient(fake_response(_good(three))))
    row = dict(conn.execute("SELECT * FROM llm_calls").fetchone())
    assert (row["stage"], row["turn_id"], row["prompt_version"]) == ("organize", None, config.PROMPT_VERSIONS["organize"])


def test_g09_organize_sends_masked_notes_only(conn, three):
    client = FakeClient(fake_response(_good(three)))
    notes.organize_notes(conn, three, client=client)
    req = client.calls[0]
    assert len(req["system"]) == 1                     # 정책만 (보고서 근거 없음)
    for n in three:
        assert n["text"] in req["messages"][0]["content"]
    assert req["messages"][0]["content"].startswith("<saved_questions>")


def _bad(three, mutate):
    out = _good(three)
    mutate(out["items"])
    return out


BAD_CASES = {
    "missing": lambda items: items.pop(),
    "duplicate": lambda items: items[1]["source_item_ids"].append(items[0]["source_item_ids"][0]),
    "unknown_id": lambda items: items[1]["source_item_ids"].append(9999),
    "new_term": lambda items: items[1].update(text="치료가 필요한지 궁금해요"),
    "new_number": lambda items: items[1].update(text="숙제를 3시간 해요"),
    "unknown_type": lambda items: items[1].update(type="smalltalk"),
    "empty_text": lambda items: items[1].update(text=" "),
}


@pytest.mark.parametrize("case", BAD_CASES, ids=list(BAD_CASES))
def test_poc2_11_invalid_then_valid_is_regen(conn, three, case):
    client = FakeClient(fake_response(_bad(three, BAD_CASES[case])), fake_response(_good(three)))
    r = notes.organize_notes(conn, three, client=client)
    assert r.source == "regen" and r.failures[0] and r.failures[1] == []


def test_poc2_11_two_failures_fall_back_to_raw_notes(conn, three):
    client = FakeClient(fake_response("not json"), fake_response(_bad(three, BAD_CASES["missing"])))
    r = notes.organize_notes(conn, three, client=client)
    assert r.source == "fallback"
    assert [i.text for i in r.items] == [n["text"] for n in three]
    assert [i.type for i in r.items] == ["diagnosis", "diagnosis", "parenting"]


def test_poc2_11_parent_wording_with_diagnosis_name_is_allowed(conn, three):
    """원래 질문에 있던 'ADHD'는 남아도 된다. 새로 생긴 금칙 표현만 막는다."""
    assert notes.validate_organized(_good(three), three, notes.load_guard_terms()) == []


def test_poc2_11_api_error_falls_back(conn, three):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    r = notes.organize_notes(conn, three, client=FakeClient(anthropic.APIConnectionError(request=req)))
    assert r.source == "fallback" and len(r.items) == 3


def test_fallback_type_mapping(conn):
    for t in ("no_evidence", "guard_fallback", "low_confidence", "api_error"):
        _note(conn, f"질문 {t}", t)
    items = notes.fallback_items(notes.list_notes(conn, CHILD))
    assert [i.type for i in items] == ["understanding", "understanding", "other", "other"]


def test_list_notes_since_turn(conn):
    first = _note(conn, "이전 세션 질문")
    _note(conn, "이번 세션 질문")
    assert [n["text"] for n in notes.list_notes(conn, CHILD, since_turn_id=first)] == ["이번 세션 질문"]


def test_organize_schema_types():
    item = notes.ORGANIZE_SCHEMA["properties"]["items"]["items"]
    assert item["properties"]["type"]["enum"] == list(notes.BRIEF_TYPES)
    assert json.dumps(notes.ORGANIZE_SCHEMA)  # 직렬화 가능
