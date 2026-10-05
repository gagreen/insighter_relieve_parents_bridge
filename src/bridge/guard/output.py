"""PoC2-08 출력 검증 [G-03, G-06, G-08] → B-4, B-6.

모델과 무관한 규칙만 쓴다. 검사 항목: 1 형식 2 근거 id 3 진단명 사전·금칙 표현 4 숫자 대조 5 범위 이름 대조.
'근거 항목'은 응답이 evidence_ids로 인용한 항목이다. 검사 종류별 분기 없음(G-12).
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from bridge.evidence import EvidencePack
from bridge.guard.terms import GuardTerm, find_violations

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


@dataclass(frozen=True)
class GuardReport:
    ok: bool
    failures: list[str]   # format:<필드> / evidence:empty / evidence:unknown:<id> / term:<id> / number:<n> / range_label:<라벨>


def _normalize(number: str) -> str:
    return format(Decimal(number).normalize(), "f")


def numbers_in(text: str) -> list[str]:
    """문장 속 숫자를 순서대로. 천 단위 쉼표를 지우고 "66.0"은 "66"으로 맞춘다."""
    return [_normalize(n) for n in _NUMBER.findall(_THOUSANDS.sub("", text))]


def _values(value) -> list:
    if isinstance(value, dict):
        return [x for k, v in value.items() if k != "id" for x in _values(v)]
    if isinstance(value, list):
        return [x for v in value for x in _values(v)]
    return [value]


def evidence_numbers(items: list[dict]) -> set[str]:
    """항목의 모든 숫자 값과 문장 속 숫자(id 제외)."""
    out = set()
    for v in _values(items):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float):
            out.add(_normalize(str(v)))
        elif isinstance(v, str):
            out.update(numbers_in(v))
    return out


def _evidence_texts(items: list[dict]) -> list[str]:
    return [v for v in _values(items) if isinstance(v, str)]


def _format_failures(parsed) -> list[str]:
    if not isinstance(parsed, dict):
        return ["format:json"]
    failures = []
    if not isinstance(parsed.get("answerable"), bool):
        failures.append("format:answerable")
    if not isinstance(parsed.get("answer"), str):
        failures.append("format:answer")
    ids = parsed.get("evidence_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        failures.append("format:evidence_ids")
    if "note_question" not in parsed or not (parsed["note_question"] is None or isinstance(parsed["note_question"], str)):
        failures.append("format:note_question")
    if not failures and parsed["answerable"] and not parsed["answer"].strip():
        failures.append("format:answer")
    return failures


def validate_answer(parsed: dict | None, pack: EvidencePack, terms: list[GuardTerm],
                    range_labels: dict[str, str]) -> GuardReport:
    """answerable=false이고 답이 비어 있으면 1·2만 확인한다(답이 화면에 나가지 않음).

    answer가 있으면(부분 답변 포함, PoC2-07) answerable과 무관하게 1~5를 모두 확인한다.
    """
    failures = _format_failures(parsed)
    if failures:
        return GuardReport(False, failures)

    ids = parsed["evidence_ids"]
    failures += [f"evidence:unknown:{i}" for i in ids if i not in pack.items]
    if not parsed["answerable"] and not parsed["answer"].strip():
        return GuardReport(not failures, failures)
    if not ids:
        failures.append("evidence:empty")

    answer = parsed["answer"]
    cited = [pack.items[i] for i in ids if i in pack.items]
    failures += [f"term:{v.term_id}" for v in find_violations(answer, terms)]

    answer_numbers = numbers_in(answer)
    allowed = evidence_numbers(cited)
    failures += [f"number:{n}" for n in dict.fromkeys(answer_numbers) if n not in allowed]

    failures += [f"range_label:{label}" for label in range_labels.values()
                 if label in answer and label not in _allowed_labels(cited, range_labels, set(answer_numbers))]
    return GuardReport(not failures, failures)


def _allowed_labels(cited: list[dict], range_labels: dict[str, str], answer_numbers: set[str]) -> set[str]:
    """인용한 점수 항목의 범위 이름 + 인용한 문장(원문·카드·용어)에 나온 범위 이름.

    기준선 라벨은 그 기준선 값이 답에 함께 나올 때만 허용한다("70부터 전문 상담 권고 범위"는 허용,
    "66으로 전문 상담 권고 범위"는 실패).
    """
    labels = {item.get("range_label") for item in cited}
    for item in cited:
        texts = _evidence_texts({k: v for k, v in item.items() if k != "thresholds"})
        labels |= {label for text in texts for label in range_labels.values() if label in text}
        for th in item.get("thresholds") or []:
            if _normalize(str(th["value"])) in answer_numbers:
                labels.add(th["label"])
    return labels
