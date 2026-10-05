"""근거 묶음 [PoC2-07, G-02, G-03, G-09]."""
import json

from bridge import config, content, evidence, results

DEF = json.loads((config.ASSESSMENT_TYPES_DIR / "KCBCL_4_17.json").read_text(encoding="utf-8"))["definition"]
BASE = json.loads(config.BASE_SAMPLE_FILE.read_text(encoding="utf-8"))
PAYLOAD = BASE["payload"]
CARDS = content.load_scale_cards()
GLOSSARY = content.load_glossary()
VIEW = results.build_view(PAYLOAD, DEF, CARDS, content.load_summary_templates(), content.load_phrases())


def _pack():
    return evidence.build_evidence(VIEW, PAYLOAD, GLOSSARY)


def test_poc2_07_pack_contains_report_items_linked_cards_and_terms():
    ids = set(_pack().items)
    linked = {i["explanation"]["card"]["id"] for i in VIEW["items"] if i["explanation"]["kind"] == "card"}
    assert {s["id"] for s in PAYLOAD["scores"]} <= ids
    assert {f["id"] for f in PAYLOAD["findings"]} <= ids
    assert {g["id"] for g in GLOSSARY} <= ids
    assert linked and linked <= ids
    assert not ({c["id"] for c in CARDS} - linked) & ids   # 연결되지 않은 범위의 카드는 넣지 않는다


def test_poc2_07_every_text_line_is_an_item_with_id():
    pack = _pack()
    lines = [json.loads(line) for line in pack.text.splitlines()]
    assert [x["id"] for x in lines] == list(pack.items)


def test_g09_pack_has_no_identifiers():
    text = _pack().text
    for value in (BASE["subject"]["name"], BASE["subject"]["name"][1:], BASE["subject"]["birth_date"],
                  BASE["child_id"], BASE["result_id"]):
        assert value not in text


def test_g03_score_numbers_are_copied_from_payload():
    items = _pack().items
    for s in PAYLOAD["scores"]:
        assert (items[s["id"]]["t"], items[s["id"]]["percentile"]) == (s["t"], s["percentile"])


def test_g02_range_label_comes_from_rules_not_payload():
    """판정 기준(group) 없는 척도는 payload에 원보고서 라벨이 있어도 범위 이름을 넣지 않는다."""
    items = _pack().items
    ungrouped = [s for s in PAYLOAD["scores"] if s["t"] is not None and "group" not in DEF["scales"][s["scale"]]]
    assert ungrouped
    for s in ungrouped:
        assert items[s["id"]]["range_label"] is None
    attention = next(s for s in PAYLOAD["scores"] if s["scale"] == "attention")
    assert items[attention["id"]]["range_label"] == DEF["range_labels"]["borderline"]


def test_g02_thresholds_come_from_definition():
    attention = next(s for s in PAYLOAD["scores"] if s["scale"] == "attention")
    th = _pack().items[attention["id"]]["thresholds"]
    group = DEF["groups"][DEF["scales"]["attention"]["group"]]
    assert [t["value"] for t in th] == [group["borderline_min"], group["clinical_min"]]


def test_poc2_07_pack_text_is_deterministic():
    """캐시 프리픽스는 바이트 단위로 같아야 한다."""
    assert _pack().text == _pack().text
