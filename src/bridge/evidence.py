"""근거 묶음 [PoC2-07, G-02, G-03, G-09].

응답 생성 프롬프트에 넣는 근거와, 출력 검증(PoC2-08)이 대조할 id·숫자의 기준을 한 곳에서 만든다.
점수는 결과 view model(규칙 판정 범위, 정의의 기준선)에서 가져오고, payload만 받으므로 식별 정보는 들어올 수 없다.
검사 종류별 분기 없음(G-12).
"""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidencePack:
    text: str                  # 한 줄에 항목 하나(JSON). 같은 입력이면 같은 바이트(캐시 프리픽스)
    items: dict[str, dict]     # id → 항목


def _threshold(t: dict, score: int | float | None) -> dict:
    """기준선 값과 이름. T점수가 있으면 차이(gap)와 위치(side)를 코드가 계산해 넣는다(모델이 계산하지 않게, G-03)."""
    out = {"value": t["value"], "label": t["label"]}
    if score is not None:
        out["gap"] = abs(score - t["value"])
        out["side"] = "at_or_above" if score >= t["value"] else "below"
    return out


def _score_item(item: dict) -> dict:
    return {
        "kind": "score", "id": item["id"], "name": item["name"],
        "t": item["t"], "percentile": item["percentile"], "rank_from_top": item["rank_from_top"],
        "range_label": item["range_label"],      # 규칙 판정 결과. 판정 기준이 없으면 null (G-02)
        "status_text": item["status_text"],
        "percentile_text": item["percentile_text"],
        "direction_note": item["direction_note"],
        "thresholds": [_threshold(t, item["t"]) for t in item["thresholds"]] if item["thresholds"] else None,
    }


def _card_item(card: dict, scale_name: str, label: str) -> dict:
    return {
        "kind": "card", "id": card["id"], "scale_name": scale_name, "label": label,
        "what_it_asks": card["what_it_asks"], "behavior_examples": card["behavior_examples"],
        "position_text": card["position_text"], "report_recommendation": card["report_recommendation"],
    }


def build_evidence(view: dict, payload: dict, glossary: list[dict]) -> EvidencePack:
    names = {i["scale"]: i["name"] for i in view["items"]}
    entries = [_score_item(i) for i in view["items"]]
    entries += [{"kind": "finding", "id": f["id"], "section": f["section"],
                 "scale_name": names.get(f["scale"]), "text": f["text"]} for f in payload["findings"]]
    entries += [_card_item(i["explanation"]["card"], i["name"], i["explanation"]["label"])
                for i in view["items"] if i["explanation"]["kind"] == "card"]
    entries += [{"kind": "term", "id": g["id"], "term": g["term"], "aliases": g["aliases"], "plain": g["plain"]}
                for g in glossary]

    items: dict[str, dict] = {}
    for e in entries:
        if e["id"] in items:
            raise ValueError(f"근거 id 중복: {e['id']}")
        items[e["id"]] = e
    text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    return EvidencePack(text, items)


def item_label(item: dict) -> str:
    """근거 칩·브리프에 쓰는 'id · 이름'. 값(점수·문장)은 넣지 않는다."""
    kind = item["kind"]
    if kind == "score":
        name = item["name"]
    elif kind == "finding":
        name = f"{item['section']} ({item['scale_name']})" if item.get("scale_name") else item["section"]
    elif kind == "card":
        name = f"{item['scale_name']} 설명 카드"
    else:
        name = item["term"]
    return f"{item['id']} · {name}"
