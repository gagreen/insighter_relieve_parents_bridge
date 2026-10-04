"""M1 쉬운 말 결과 조립 (PoC1-03 한 줄 요약, PoC1-04 척도 설명 카드).

미리 만든 문장을 조립만 한다(G-04). LLM을 호출하지 않는다. 검사 종류별 분기 없음(G-12).
"""
from bridge.content import CARD_SENTENCE_FIELDS
from bridge.rules.ranges import BORDERLINE, CLINICAL, judge

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
