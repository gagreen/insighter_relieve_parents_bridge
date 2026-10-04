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


def _score_item(item: dict) -> dict:
    return {
        "kind": "score", "id": item["id"], "name": item["name"],
        "t": item["t"], "percentile": item["percentile"], "rank_from_top": item["rank_from_top"],
        "range_label": item["range_label"],      # 규칙 판정 결과. 판정 기준이 없으면 null (G-02)
        "status_text": item["status_text"],
        "percentile_text": item["percentile_text"],
        "direction_note": item["direction_note"],
        "thresholds": [{"value": t["value"], "label": t["label"]} for t in item["thresholds"]]
        if item["thresholds"] else None,
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
