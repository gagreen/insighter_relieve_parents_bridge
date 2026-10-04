"""M1 쉬운 말 결과 조립 (PoC1-02~07: 숫자 표시, 한 줄 요약, 카드, 미실시, 기준선, 고정 문구).

미리 만든 문장을 조립만 한다(G-04). LLM을 호출하지 않는다. 검사 종류별 분기 없음(G-12).
"""
from bridge.content import CARD_SENTENCE_FIELDS
from bridge.rules.ranges import BORDERLINE, CLINICAL, NOT_ADMINISTERED, direction, judge

DRAFT_LABEL = "초안(검수 전)"      # G-04, G-11
REVIEWED_LABEL = "검수된 설명"     # G-11


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
    """PoC1-04: (scale, range) 카드 1장을 붙인다. 없으면 같은 scale의 보고서 원문을 그대로 쓴다."""
    card = next((c for c in cards if c["assessment"] == assessment
                 and c["scale"] == score["scale"] and c["range"] == judged_range), None)
    if card is not None:
        label = DRAFT_LABEL if card["status"] == "draft" else REVIEWED_LABEL
        return {"kind": "card", "card": render_card(card, score, definition), "label": label}
    matched = [f for f in findings if f.get("scale") == score["scale"]]
    return {"kind": "report_text", "finding_ids": [f["id"] for f in matched], "texts": [f["text"] for f in matched]}


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


def build_view(payload: dict, definition: dict, cards: list[dict], templates: list[dict], phrases: dict) -> dict:
    """결과 화면 데이터. 숫자는 payload에서 복사만 한다(G-03). 항목을 숨기지 않는다(PoC1-05).

    payload만 받으므로 식별 정보(subjects)는 들어올 수 없다(G-09).
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
    return {"notice": phrases["fixed_notice_results"], "summary": summarize(judged, templates), "items": items}
