# -*- coding: utf-8 -*-
"""
data/kcbcl_samples_100.json (원본, 수정하지 않음) -> 공통 뼈대 형식 변환

공통 뼈대: CLAUDE.md 8-1 (docs/claude-md-draft.md "JSON 공통 뼈대" + extra 필드, range 영문 enum)
- 숫자는 scores, 문장은 findings, 파일은 files. 검사별 부가 정보는 항목의 extra.
- 서술은 원문 문장 그대로 text에 넣는다(요약·재작성 없음).
- 모든 항목에 고유 id. id 접두어는 보고서 섹션 번호(Ⅰ~Ⅶ)를 따른다.
- range: normal | borderline | clinical | not_administered
- 식별 정보(이름·생년월일·학년)는 payload 밖 subject 블록에 둔다(G-09: 외부 API로 보내지 않음).

출력 (실제 데이터처럼 검사 결과 1건 = 파일 1개):
  data/kcbcl_results/001.json ~ 100.json   검사 결과 1건 (subject + payload + sample_meta)
  data/assessment_types/KCBCL_4_17.json    검사 정의 (척도 목록·범위 판정 기준)

사용법: python scripts/convert_kcbcl_to_skeleton.py [입력] [결과 폴더] [검사 정의 폴더]
"""
import json
import math
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "data/kcbcl_samples_100.json"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "data/kcbcl_results"
TYPE_DIR = sys.argv[3] if len(sys.argv) > 3 else "data/assessment_types"

ASSESSMENT_CODE = "KCBCL_4_17"
SCHEMA_VERSION = 1
RANGE_MAP = {"정상": "normal", "준임상": "borderline", "임상": "clinical", None: "not_administered"}

SECTION = {
    "H": "기본 정보",
    "I": "사회능력 척도",
    "II": "문제행동 종합 지표",
    "III": "증후군 척도 프로파일",
    "IV": "특수 척도",
    "V": "주요 관찰 소견",
    "VI": "종합 해석",
    "VII": "보호자 참고 의견",
    "C": "해석 시 유의사항",
}

# 원본 key_findings·guardian_comments의 특수척도 키 -> scores의 scale 키로 통일
SCALE_ALIAS = {"emoinst": "emotional_instability", "sexprob": "sex_problems"}

SYNDROME_ORDER = ["withdrawn", "somatic", "anxdep", "socimm", "thought", "attention", "delinquent", "aggressive"]
COMPOSITE_ORDER = ["internalizing", "externalizing", "total"]
SPECIAL = {
    "emotional_instability": {"name": "정서불안정", "name_en": "Emotional Instability", "items": 10,
                              "age_min": 6, "age_max": 11},
    "sex_problems": {"name": "성문제", "name_en": "Sex Problems", "items": 6, "age_min": 4, "age_max": 11},
}
SOCIAL = {
    "sociability": {"name": "사회성", "name_en": "Sociability"},
    "school_performance": {"name": "학업수행", "name_en": "School Performance"},
    "total_competence": {"name": "총 사회능력", "name_en": "Total Competence"},
}
COMP_EN = {"internalizing": "Internalizing", "externalizing": "Externalizing", "total": "Total Problems"}
COMP_PARTS = {"internalizing": ["withdrawn", "somatic", "anxdep"],
              "externalizing": ["delinquent", "aggressive"], "total": None}


def pct_int(p):
    """백분위 정수화(사사오입). 99.5 초과는 99로 두고 extra.percentile_text(">99")로 구분.
    원본의 소수 1자리 값(예: 94.5)을 다시 반올림하면 은행가 반올림으로 94가 되어
    보고서 문장("약 95%tile")과 어긋나므로, 항상 T점수에서 직접 계산한 값을 넣는다."""
    if p is None:
        return None
    return min(99, max(1, int(math.floor(p + 0.5))))


def pct_from_t(t, floor50=False):
    """정규분포 기준 T점수 -> 백분위 (원본과 같은 산식). 하한 50T 척도의 50T는 null."""
    if t is None or (floor50 and t <= 50):
        return None
    return 50 * (1 + math.erf((t - 50) / 10 / math.sqrt(2)))


def pct_text(t, floor50=False):
    p = pct_from_t(t, floor50)
    if p is None:
        return "≤50" if floor50 else None
    return ">99" if p > 99.5 else ("<1" if p < 1 else str(int(round(p))))


def assessment_type_definition(meta):
    """assessment_types 시드 1행. definition 형식은 specs/poc.md 2-2를 따른다.

    - scales 키 = payload scores[].scale 키 = 원천 데이터 키.
    - PoC 시드에는 종합척도·증후군 척도 기준(group)만 넣는다(2-2). 특수척도·사회능력 기준은
      참고 보고서에 없는 가정값이라 넣지 않는다(해당 scores의 range는 원보고서 라벨 그대로 둠).
    - 판정 기준 없는 척도는 group 없이 direction만 둔다(백분위 문장 방향용, PoC1-02).
    """
    syn = meta["scales"]["syndromes"]
    scales = {k: {"group": "composite"} for k in COMPOSITE_ORDER}
    scales.update({s["key"]: {"group": "syndrome"} for s in syn})
    scales.update({k: {"direction": "higher_is_worse"} for k in SPECIAL})
    scales.update({k: {"direction": "lower_is_worse"} for k in SOCIAL})
    return {
        "code": ASSESSMENT_CODE,
        "name": "K-CBCL 한국 아동·청소년 행동평가척도 (보호자 보고형, 만 4–17세)",
        "respondent": "부모",
        "schema_version": SCHEMA_VERSION,
        "definition": {
            "range_labels": {"normal": "또래 평균 범위", "borderline": "관찰 권고 범위",
                             "clinical": "전문 상담 권고 범위", "not_administered": "미실시"},
            "groups": {
                "composite": {"direction": "higher_is_worse", "borderline_min": 60, "clinical_min": 63},
                "syndrome": {"direction": "higher_is_worse", "borderline_min": 60, "clinical_min": 70},
            },
            "scales": scales,
        },
    }


def score(id_, scale, name, t, pct, range_ko, extra):
    return {"id": id_, "scale": scale, "name": name, "t": t, "percentile": pct,
            "range": RANGE_MAP[range_ko], "extra": extra}


def finding(id_, ftype, sec, scale, text, extra=None):
    f = {"id": id_, "type": ftype, "section": SECTION[sec], "scale": scale, "text": text}
    f["extra"] = extra or {}
    return f


def convert_sample(s, cautions):
    c = s["child"]
    scores, findings = [], []

    # Ⅰ. 사회능력 척도
    sc = s["social_competence"]
    for k, v in SOCIAL.items():
        item = sc.get(k) if sc["administered"] else None
        extra = {"group": "social_competence", "name_en": v["name_en"], "direction": "lower_is_worse"}
        if item is None:
            extra["reason"] = ("미실시" if not sc["administered"] else "적용 대상 아님(초등학생 이상 적용)")
            scores.append(score(f"I.{k}", k, v["name"], None, None, None, extra))
        else:
            extra["percentile_text"] = pct_text(item["t"])
            scores.append(score(f"I.{k}", k, v["name"], item["t"], pct_int(pct_from_t(item["t"])), item["range"], extra))
    if sc.get("note"):
        findings.append(finding("I.note", "note", "I", None, sc["note"]))

    # Ⅱ. 문제행동 종합 지표
    for k in COMPOSITE_ORDER:
        v = s["composite_scales"][k]
        scores.append(score(f"II.{k}", k, v["name_ko"], v["t"], pct_int(pct_from_t(v["t"])), v["range"], {
            "group": "composite", "name_en": COMP_EN[k], "raw": v["raw"],
            "percentile_text": v["percentile_text"], "components": COMP_PARTS[k],
        }))
    findings.append(finding("II.summary", "narrative", "II", None, s["composite_summary"]))

    # Ⅲ. 증후군 척도
    syn = {x["key"]: x for x in s["syndrome_scales"]}
    for k in SYNDROME_ORDER:
        v = syn[k]
        scores.append(score(f"III.{k}", k, v["name_ko"], v["t"], pct_int(pct_from_t(v["t"], True)), v["range"], {
            "group": "syndrome", "name_en": v["name_en"], "domain": v["domain"], "items": v["items"],
            "raw": v["raw"], "max_raw": v["max_raw"], "percentile_text": v["percentile_text"],
        }))

    # Ⅳ. 특수 척도
    for k, d in SPECIAL.items():
        v = s["special_scales"][k]
        extra = {"group": "special", "name_en": d["name_en"], "items": d["items"],
                 "eligible": v["eligible"], "age_range": f"{d['age_min']}–{d['age_max']}세"}
        if v["administered"]:
            extra["raw"] = v["raw"]
            extra["percentile_text"] = pct_text(v["t"], True)
            scores.append(score(f"IV.{k}", k, d["name"], v["t"], pct_int(pct_from_t(v["t"], True)), v["range"], extra))
        else:
            extra["reason"] = "미실시" if v["eligible"] else "적용 연령 아님"
            scores.append(score(f"IV.{k}", k, d["name"], None, None, None, extra))
        findings.append(finding(f"IV.{k}.note", "note", "IV", k, v["note"]))

    # 기본 정보 (식별 정보 제외: 이름·생년월일·학년은 subjects로 분리)
    findings.append(finding("H.sex_age", "info", "H", None,
                            f"{'남아' if c['sex'] == '남' else '여아'} / {c['age_text']}",
                            {"sex": c["sex"], "age_years": c["age_years"], "age_months": c["age_months"]}))
    findings.append(finding("H.norm_group", "info", "H", None, s["norm_group"]))
    findings.append(finding("H.informant", "info", "H", None, s["informant"]))

    # Ⅴ. 주요 관찰 소견 — 항목당 1개, points는 원문 그대로 줄바꿈으로 연결
    used = set()
    for f in s["key_findings"]:
        scale = SCALE_ALIAS.get(f["scale"], f["scale"])
        fid = f"V.{scale}" if scale else "V.overall"
        if fid in used:
            raise ValueError(f"duplicate finding id {fid} in {s['id']}")
        used.add(fid)
        findings.append(finding(fid, "observation", "V", scale, "\n".join(f["points"]),
                                {"title": f["title"], "badge": f["badge"], "t": f["t"]}))

    # Ⅵ. 종합 해석 — 문단 단위
    for i, para in enumerate(s["overall_interpretation"].split("\n\n"), 1):
        findings.append(finding(f"VI.p{i}", "narrative", "VI", None, para))
    for i, r in enumerate(s["recommended_follow_up"], 1):
        findings.append(finding(f"VI.rec{i}", "recommendation", "VI", None, r))

    # Ⅶ. 보호자 참고 의견
    for i, cm in enumerate(s["guardian_comments"], 1):
        findings.append(finding(f"VII.{i}", "guardian_comment", "VII",
                                SCALE_ALIAS.get(cm["related_scale"], cm["related_scale"]), cm["text"],
                                {"tag": cm["tag"]}))

    # 해석 시 유의사항 (보고서 공통 문구)
    for i, txt in enumerate(cautions, 1):
        findings.append(finding(f"C.{i}", "caution", "C", None, txt))

    payload = {
        "assessment": ASSESSMENT_CODE,
        "schema_version": SCHEMA_VERSION,
        "scores": scores,
        "findings": findings,
        "files": [],
    }
    num = s["id"].rsplit("-", 1)[-1]
    child_id = f"C-{num}"
    subject = {
        "child_id": child_id, "name": c["name"], "sex": c["sex"], "birth_date": c["birth_date"],
        "school_level": c["school_level"], "grade": c["grade"],
    }
    result = {
        "result_id": f"R-{ASSESSMENT_CODE}-{num}",
        "child_id": child_id,
        "assessment_code": ASSESSMENT_CODE,
        "administered_at": s["test_date"],
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "payload": payload,
        "sample_meta": {
            "synthetic": True,
            "source_id": s["id"],
            "severity_tier": s["sample_meta"]["severity_tier"],
            "profile_type": s["sample_meta"]["profile_type"],
            "referral_reason": s["referral_reason"],
            "expected_flags": s["summary_flags"],
        },
    }
    return num, result


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def main():
    src = json.load(open(SRC, encoding="utf-8"))
    meta = src["metadata"]
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TYPE_DIR, exist_ok=True)
    nums = []
    for s in src["samples"]:
        num, res = convert_sample(s, meta["report_cautions"])
        dump(os.path.join(OUT_DIR, f"{num}.json"), res)
        nums.append(num)
    atype = assessment_type_definition(meta)
    dump(os.path.join(TYPE_DIR, f"{ASSESSMENT_CODE}.json"), atype)
    print(f"written {len(nums)} files ({nums[0]}~{nums[-1]}) -> {OUT_DIR}/, definition -> {TYPE_DIR}/")


if __name__ == "__main__":
    main()
