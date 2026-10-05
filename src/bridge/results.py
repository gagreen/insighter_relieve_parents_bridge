"""M1 쉬운 말 결과 조립 (PoC1-02~07: 숫자 표시, 한 줄 요약, 카드, 미실시, 기준선, 고정 문구).

미리 만든 문장을 조립만 한다(G-04). LLM을 호출하지 않는다. 검사 종류별 분기 없음(G-12).
"""
from bridge.content import CARD_SENTENCE_FIELDS
from bridge.rules.glossary_match import annotate
from bridge.rules.ranges import BORDERLINE, CLINICAL, NOT_ADMINISTERED, direction, judge

DRAFT_LABEL = "초안(검수 전)"      # G-04, G-11
REVIEWED_LABEL = "검수된 설명"     # G-11
OTHER_SECTION = {"key": "_other", "title": "기타"}   # 정의에 없는 접두어 (PoC1-09)


def judge_scores(scores: list[dict], definition: dict) -> list[dict]:
    """payload scores를 규칙으로 판정한다(G-02). 정의 없는 척도는 range=None."""
    return [{"id": s["id"], "scale": s["scale"], "name": s["name"],
             "range": judge(s["scale"], s["t"], definition)} for s in scores]


def summarize(judged: list[dict], templates: list[dict]) -> dict:
    """PoC1-03: 임상 × 준임상 존재 여부로 템플릿 1개를 고르고 척도 이름으로 채운다."""
    clinical = [j["name"] for j in judged if j["range"] == CLINICAL]
    borderline = [j["name"] for j in judged if j["range"] == BORDERLINE]
    when = {"has_clinical": bool(clinical), "has_borderline": bool(borderline)}
    template = next(t for t in templates if t["when"] == when)
    text = template["text"].format_map({
        "clinical_list": ", ".join(clinical),
        "borderline_list": ", ".join(borderline),
    })
    return {"template_id": template["id"], "text": text}


def render_card(card: dict, score: dict, definition: dict) -> dict:
    """카드 자리표시자를 채운다: {scale_name} ← payload name, {range_label} ← 정의 range_labels."""
    values = {"scale_name": score["name"], "range_label": definition["range_labels"][card["range"]]}
    rendered = dict(card)
    for field in CARD_SENTENCE_FIELDS:
        v = card[field]
        rendered[field] = v.format_map(values) if isinstance(v, str) else [s.format_map(values) for s in v]
    return rendered


def link_card(score: dict, judged_range: str | None, cards: list[dict],
              findings: list[dict], definition: dict, assessment: str) -> dict:
    """PoC1-04: (scale, range) 카드 1장을 붙인다. 없으면 같은 scale의 원문이 있는 섹션을 안내한다.

    원문 자체는 섹션 배치(PoC1-09)에 한 번만 나오므로 여기서 다시 싣지 않는다(2026-10-05).
    """
    card = next((c for c in cards if c["assessment"] == assessment
                 and c["scale"] == score["scale"] and c["range"] == judged_range), None)
    if card is not None:
        label = DRAFT_LABEL if card["status"] == "draft" else REVIEWED_LABEL
        return {"kind": "card", "card": render_card(card, score, definition), "label": label}
    matched = [f for f in findings if f.get("scale") == score["scale"]]
    titles = [section_of(f["id"], definition)["title"] for f in matched]
    return {"kind": "report_ref", "finding_ids": [f["id"] for f in matched],
            "section_titles": [t for t in dict.fromkeys(titles) if t]}


def thresholds(scale: str, definition: dict) -> list[dict] | None:
    """PoC1-06: 기준선 값은 정의에서만 읽는다(G-02). group 없는 척도는 None."""
    scale_def = definition["scales"].get(scale, {})
    if "group" not in scale_def:
        return None
    group = definition["groups"][scale_def["group"]]
    suffix = "min" if group["direction"] == "higher_is_worse" else "max"
    return [{"value": group[f"{r}_{suffix}"], "range": r, "label": definition["range_labels"][r]}
            for r in (BORDERLINE, CLINICAL)]


def t_floor(scale: str, definition: dict) -> int | None:
    """그룹의 T점수 하한(spec 2-2 t_floor). 없으면 None."""
    group = definition["scales"].get(scale, {}).get("group")
    return definition["groups"][group].get("t_floor") if group else None


def percentile_text(score: dict, scale_direction: str | None, phrases: dict,
                    floor: int | None = None) -> tuple[str | None, int | None]:
    """PoC1-02: 방향에 맞는 백분위 문장과 rank_from_top(100 − 백분위)을 돌려준다."""
    t, p = score["t"], score["percentile"]
    if t is None or scale_direction is None:
        return None, None
    if p is None:
        # 하한(정의의 t_floor)일 때만 하한 설명. 원보고서에 백분위가 없는 경우는 숫자만 둔다(2026-10-05).
        at_floor = floor is not None and t == floor and scale_direction == "higher_is_worse"
        return (phrases["percentile_unknown"], None) if at_floor else (None, None)
    if scale_direction == "higher_is_worse":
        rank = 100 - p
        return phrases["percentile_known"].format(rank_from_top=rank), rank
    return phrases["percentile_known_lower"].format(percentile=p), None


def section_key(item_id: str) -> str:
    """항목 id의 접두어(첫 '.' 앞, CLAUDE.md 8-1)."""
    return item_id.split(".", 1)[0]


def section_of(item_id: str, definition: dict) -> dict:
    """정의 report_sections에서 항목의 섹션. 정의에 섹션이 없으면 제목 없는 섹션, 없는 접두어면 '기타'."""
    sections = definition.get("report_sections")
    if not sections:
        return {"key": "_all", "title": None}
    return next((s for s in sections if s["key"] == section_key(item_id)), OTHER_SECTION)


def _finding_block(f: dict, items_by_scale: dict[str, dict], score_section: dict[str, str],
                   definition: dict, glossary: list[dict] | None) -> dict:
    """문장 블록. 다른 섹션에 점수가 있는 scale이면 제목(이름 · T · 범위 이름)을 view 항목에서 채운다(G-03)."""
    heading = None
    item = items_by_scale.get(f.get("scale"))
    if item is not None and score_section[item["id"]] != section_of(f["id"], definition)["key"]:
        heading = {"item_id": item["id"], "name": item["name"], "t": item["t"], "range_label": item["range_label"]}
    segments = annotate(f["text"], glossary) if glossary else [{"text": f["text"], "term_id": None}]
    return {"kind": "finding", "id": f["id"], "type": f.get("type"), "scale": f.get("scale"),
            "text": f["text"], "heading": heading, "segments": segments}


def build_sections(items: list[dict], findings: list[dict], definition: dict,
                   glossary: list[dict] | None = None) -> list[dict]:
    """PoC1-09: 정의 report_sections 순서로 점수 → 문장을 배치한다. 모든 항목이 정확히 한 번 나온다.

    섹션 소속은 id 접두어. 섹션 안 순서는 payload 순서이고, subgroups가 있으면 소제목 + 정의 순서의 척도.
    """
    order = [*(definition.get("report_sections") or [{"key": "_all", "title": None}]), OTHER_SECTION]
    score_section = {i["id"]: section_of(i["id"], definition)["key"] for i in items}
    items_by_scale = {i["scale"]: i for i in items}
    sections = []
    for sec in order:
        sec_items = [i for i in items if score_section[i["id"]] == sec["key"]]
        sec_findings = [f for f in findings if section_of(f["id"], definition)["key"] == sec["key"]]
        if not sec_items and not sec_findings:
            continue
        blocks = []
        placed = set()
        for group in sec.get("subgroups", []):
            members = [i for scale in group["scales"] for i in sec_items if i["scale"] == scale]
            if members:
                blocks.append({"kind": "subgroup", "title": group["title"]})
                blocks += [{"kind": "score", "id": i["id"]} for i in members]
                placed.update(i["id"] for i in members)
        blocks += [{"kind": "score", "id": i["id"]} for i in sec_items if i["id"] not in placed]
        blocks += [_finding_block(f, items_by_scale, score_section, definition, glossary) for f in sec_findings]
        sections.append({"key": sec["key"], "title": sec["title"], "blocks": blocks})
    return sections


def build_view(payload: dict, definition: dict, cards: list[dict], templates: list[dict], phrases: dict,
               glossary: list[dict] | None = None) -> dict:
    """결과 화면 데이터. 숫자는 payload에서 복사만 한다(G-03). 항목을 숨기지 않는다(PoC1-05).

    payload만 받으므로 식별 정보(subjects)는 들어올 수 없다(G-09).
    glossary를 주면 문장 블록에 낱말 풀이 구간(PoC1-10)을 붙인다.
    """
    judged = judge_scores(payload["scores"], definition)
    items = []
    for s, j in zip(payload["scores"], judged):
        d = direction(s["scale"], definition)
        p_text, rank = percentile_text(s, d, phrases, t_floor(s["scale"], definition))
        not_administered = j["range"] == NOT_ADMINISTERED
        items.append({
            "id": s["id"], "scale": s["scale"], "name": s["name"],
            "t": s["t"], "percentile": s["percentile"], "rank_from_top": rank,
            "range": j["range"],
            "range_label": definition["range_labels"][j["range"]] if j["range"] else None,
            "status": "not_administered" if not_administered else "scored",
            "status_text": phrases["not_administered"] if not_administered else None,
            "direction": d,
            "percentile_text": p_text,
            "direction_note": phrases["direction_note_lower"] if d == "lower_is_worse" and s["t"] is not None else None,
            "thresholds": thresholds(s["scale"], definition),
            "explanation": link_card(s, j["range"], cards, payload["findings"], definition, payload["assessment"]),
        })
    return {"notice": phrases["fixed_notice_results"], "summary": summarize(judged, templates), "items": items,
            "sections": build_sections(items, payload["findings"], definition, glossary)}
