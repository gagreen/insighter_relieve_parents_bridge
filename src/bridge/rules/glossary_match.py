"""낱말 풀이 구간 (PoC1-10) [G-03, G-04].

보고서 원문은 고치지 않고, 용어사전의 표현(term·aliases 글자 그대로, patterns 정규식)에 걸린 자리에 용어 id를 붙인다.
LLM을 호출하지 않는다. 검사 종류별 분기 없음(G-12).
"""
import re


def _matches(text: str, glossary: list[dict]) -> list[tuple[int, int, str]]:
    found = []
    for g in glossary:
        for word in [g["term"], *g["aliases"]]:
            found += [(m.start(), m.end(), g["id"]) for m in re.finditer(re.escape(word), text)]
        for pattern in g.get("patterns", []):
            found += [(m.start(), m.end(), g["id"]) for m in re.finditer(pattern, text) if m.end() > m.start()]
    return found


def annotate(text: str, glossary: list[dict]) -> list[dict]:
    """[{text, term_id}] 구간. 이어 붙이면 원문과 같다.

    겹치면 긴 표현이 먼저(같으면 앞자리), 같은 용어는 문장마다 첫 자리 한 번만 붙인다.
    """
    chosen: list[tuple[int, int, str]] = []
    for start, end, term_id in sorted(_matches(text, glossary), key=lambda m: (m[0] - m[1], m[0])):
        if all(end <= s or start >= e for s, e, _ in chosen):
            chosen.append((start, end, term_id))
    seen: set[str] = set()
    first = []
    for start, end, term_id in sorted(chosen):
        if term_id not in seen:
            seen.add(term_id)
            first.append((start, end, term_id))

    segments, pos = [], 0
    for start, end, term_id in first:
        if start > pos:
            segments.append({"text": text[pos:start], "term_id": None})
        segments.append({"text": text[start:end], "term_id": term_id})
        pos = end
    if pos < len(text):
        segments.append({"text": text[pos:], "term_id": None})
    return segments


def term_ids(segments: list[dict]) -> list[str]:
    return [s["term_id"] for s in segments if s["term_id"]]
