# -*- coding: utf-8 -*-
"""
K-CBCL 가상 검사 결과 샘플 생성기 (PoC 테스트용)

- 구조/해석 기준: 'AI개발자_테스트자료_CBCL보고서' (K-CBCL 결과 보고서 샘플)를 따름
- 원점수 -> T점수 변환은 실제 K-CBCL 규준표가 아닌 '시뮬레이션 규준'을 사용함
  (지역사회 표본을 잠재요인 모델로 모의 생성 후 백분위 기반 정규화 T점수로 변환)
- 모든 인적 정보는 가상
- 서술 문형은 자체 문장이다. 회사 제공 보고서(공유 금지)와 겹치던 문형은 2026-10-06에 다시 썼다 (specs/poc.md 2-3-1)
- 100건을 생성하되 평가 샘플 10건(PUBLISHED)만 kcbcl_samples.json으로 내보낸다. data/ 에서 실행한다
"""
import json
import math
import random
from datetime import date, timedelta
from statistics import NormalDist

SEED = 20261002
# 공개하는 샘플 번호 = 평가 샘플(eval/samples.json). 생성은 100건 그대로 해 번호·점수가 바뀌지 않게 한다 (specs/poc.md 2-3-1)
PUBLISHED = {"001", "003", "005", "006", "008", "011", "016", "023", "035", "065"}
N_SAMPLES = 100
NORM_POP = 40000
ND = NormalDist()

# --------------------------------------------------------------------------------------
# 척도 정의 (참고 보고서 기준: 문항 수, 소속 영역)
# --------------------------------------------------------------------------------------
SYNDROMES = [
    # key, 한글명, 영문명, 문항수, 영역, 조사(이/가)
    ("withdrawn", "위축", "Withdrawn", 9, "내재화", "이"),
    ("somatic", "신체증상", "Somatic Complaints", 9, "내재화", "이"),
    ("anxdep", "우울/불안", "Depressed/Anxious", 14, "내재화", "이"),
    ("socimm", "사회적 미성숙", "Social Immaturity", 8, "혼합", "이"),
    ("thought", "사고의 문제", "Thought Problems", 7, "혼합", "가"),
    ("attention", "주의집중 문제", "Attention Problems", 11, "혼합", "가"),
    ("delinquent", "비행", "Delinquent", 13, "외현화", "이"),
    ("aggressive", "공격성", "Aggressive", 20, "외현화", "이"),
]
SYN = {s[0]: s for s in SYNDROMES}
OTHER_ITEMS = 117 - sum(s[3] for s in SYNDROMES)  # 총 문제행동 117문항 중 증후군 미포함 문항

# 시뮬레이션 규준: (남 4-11세 기준 원점수 평균, 표준편차) — 실제 규준 아님
BASE_NORM = {
    "withdrawn": (2.0, 2.0), "somatic": (1.0, 1.5), "anxdep": (3.5, 3.5),
    "socimm": (2.0, 2.0), "thought": (0.6, 1.0), "attention": (3.5, 3.2),
    "delinquent": (1.2, 1.5), "aggressive": (7.0, 5.6), "other": (4.0, 3.0),
    "emoinst": (3.0, 3.0), "sexprob": (0.5, 0.9),
}
MAX_RAW = {k: SYN[k][3] * 2 for k in SYN}
MAX_RAW.update({"other": OTHER_ITEMS * 2, "emoinst": 20, "sexprob": 12})

# 규준집단별 원점수 평균 배수 (성별·연령 차이 반영, 시뮬레이션)
GROUP_MULT = {
    ("남", "4-11"): {"attention": 1.15, "aggressive": 1.15, "delinquent": 1.1},
    ("여", "4-11"): {"anxdep": 1.05, "somatic": 1.1, "aggressive": 0.9, "attention": 0.85},
    ("남", "12-17"): {"delinquent": 1.5, "somatic": 1.2, "withdrawn": 1.3, "socimm": 0.7,
                      "aggressive": 0.95, "attention": 1.0},
    ("여", "12-17"): {"delinquent": 1.2, "somatic": 1.5, "withdrawn": 1.35, "anxdep": 1.25,
                      "socimm": 0.7, "aggressive": 0.85, "attention": 0.85},
}

# 잠재요인 적재치: g(일반), INT(내재화), EXT(외현화), ATT(주의/충동)
LOADINGS = {
    "withdrawn": ({"g": .5, "INT": .6}, .62),
    "somatic": ({"g": .4, "INT": .45}, .80),
    "anxdep": ({"g": .5, "INT": .7}, .50),
    "socimm": ({"g": .55, "ATT": .3, "INT": .2}, .70),
    "thought": ({"g": .5}, .85),
    "attention": ({"g": .5, "ATT": .7}, .50),
    "delinquent": ({"g": .5, "EXT": .6}, .62),
    "aggressive": ({"g": .55, "EXT": .65, "ATT": .2}, .45),
    "other": ({"g": .7}, .70),
    "emoinst": ({"g": .5, "EXT": .35, "INT": .35}, .60),
    "sexprob": ({"g": .3}, .95),
}
FACTORS = ["g", "INT", "EXT", "ATT"]


def raw_score(key, f, rng, group, boost=0.0):
    loads, uniq = LOADINGS[key]
    var = sum(v * v for v in loads.values()) + uniq * uniq
    s = sum(loads[k] * f.get(k, 0.0) for k in loads) + uniq * rng.gauss(0, 1)
    z = s / math.sqrt(var) + boost
    m, sd = BASE_NORM[key]
    m *= GROUP_MULT[group].get(key, 1.0)
    c = math.sqrt(math.log(1 + (sd / BASE_NORM[key][0]) ** 2))
    x = m * math.exp(c * z - c * c / 2)
    r = int(math.floor(x + rng.random()))
    return max(0, min(MAX_RAW[key], r))


# --------------------------------------------------------------------------------------
# 시뮬레이션 규준 생성
# --------------------------------------------------------------------------------------
class Norm:
    def __init__(self, values):
        self.n = len(values)
        self.counts = {}
        for v in values:
            self.counts[v] = self.counts.get(v, 0) + 1
        self.maxv = max(values)
        self.cum_below = {}
        acc = 0
        for v in range(0, self.maxv + 2):
            self.cum_below[v] = acc
            acc += self.counts.get(v, 0)

    def pct(self, x):
        if x > self.maxv:
            return None
        below = self.cum_below.get(x, 0)
        eq = self.counts.get(x, 0)
        return (below + 0.5 * eq) / self.n

    def t_score(self, x, floor50):
        p = self.pct(x)
        if p is None:  # 규준 표본 최대값을 넘는 극단 점수: 선형 연장
            top = 50 + 10 * ND.inv_cdf(1 - 0.5 / self.n)
            t = top + 2.0 * (x - self.maxv)
        else:
            p = min(max(p, 0.001), 0.9999)
            t = 50 + 10 * ND.inv_cdf(p)
        t = int(round(t))
        if floor50:
            t = max(50, t)
        return max(30, min(100, t))


def build_norms(rng):
    norms = {}
    for group in GROUP_MULT:
        cols = {k: [] for k in list(SYN) + ["other", "emoinst", "sexprob", "INT", "EXT", "TOT"]}
        for _ in range(NORM_POP):
            f = {k: rng.gauss(0, 1) for k in FACTORS}
            r = {k: raw_score(k, f, rng, group) for k in list(SYN) + ["other", "emoinst", "sexprob"]}
            for k, v in r.items():
                cols[k].append(v)
            cols["INT"].append(r["withdrawn"] + r["somatic"] + r["anxdep"])
            cols["EXT"].append(r["delinquent"] + r["aggressive"])
            cols["TOT"].append(sum(r[k] for k in SYN) + r["other"])
        norms[group] = {k: Norm(v) for k, v in cols.items()}
    return norms


# --------------------------------------------------------------------------------------
# 판정 기준 (참고 보고서)
# --------------------------------------------------------------------------------------
def composite_range(t):
    return "임상" if t >= 63 else ("준임상" if t >= 60 else "정상")


def syndrome_range(t):
    return "임상" if t >= 70 else ("준임상" if t >= 60 else "정상")


def competence_range(t, total):
    # 임상 기준: 총점 ≤33T, 하위척도 ≤30T (참고 보고서)
    # 준임상(경계) 구간은 보고서에 없어 ASEBA 관례를 참고한 가정: 총점 34-40T, 하위 31-35T
    if total:
        return "임상" if t <= 33 else ("준임상" if t <= 40 else "정상")
    return "임상" if t <= 30 else ("준임상" if t <= 35 else "정상")


def pct_of(t):
    return ND.cdf((t - 50) / 10) * 100


def pct_text(t, syndrome=False):
    if syndrome and t <= 50:
        return "≤50"
    p = pct_of(t)
    if p > 99.5:
        return ">99"
    if p < 1:
        return "<1"
    return str(int(round(p)))


def ro(n):
    """숫자 뒤 조사 (으)로: 끝자리 0·3·6 및 100은 '으로'"""
    return "으로" if (n % 10 in (0, 3, 6)) else "로"


def ptile(t, syndrome=False):
    p = pct_text(t, syndrome)
    return "99%tile 초과" if p == ">99" else f"약 {p}%tile"


def pct_num(t, syndrome=False):
    if syndrome and t <= 50:
        return None
    return round(pct_of(t), 1)


# --------------------------------------------------------------------------------------
# 인적 정보
# --------------------------------------------------------------------------------------
SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권",
            "황", "안", "송", "류", "전", "홍", "고", "문", "양", "손", "배", "백", "허", "남", "심"]
GIVEN_M = ["도윤", "서준", "하준", "은우", "시우", "지호", "예준", "유준", "수호", "이준", "건우", "지환",
           "우진", "선우", "연우", "민재", "현우", "정우", "윤호", "태윤", "주원", "승민", "재원", "한결",
           "로운", "시윤", "준서", "민준", "지안", "태오"]
GIVEN_F = ["서아", "하윤", "지안", "아린", "지우", "서윤", "하은", "수아", "윤서", "채원", "다은", "예린",
           "소율", "나은", "시은", "유나", "가은", "지유", "하린", "예서", "수빈", "민서", "서연", "채윤",
           "은서", "다인", "리아", "주아", "세아", "유진"]
INFORMANTS = [("어머니", 68), ("아버지", 22), ("할머니", 6), ("할아버지", 1), ("기타 주 양육자", 3)]


def weighted(rng, pairs):
    tot = sum(w for _, w in pairs)
    x = rng.uniform(0, tot)
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


def school_info(birth, test):
    # 한국 학제: 출생연도 + 7년의 3월 초등 입학. 1~2월 검사는 직전 학년도.
    school_year = test.year if test.month >= 3 else test.year - 1
    idx = school_year - birth.year - 6
    if idx <= 0:
        kg_age = 7 + idx  # 0 -> 7세반, -1 -> 6세반, -2 -> 5세반 (한국 나이 기준 반 명칭)
        return "preschool", f"유치원 {kg_age}세반" if kg_age >= 5 else "어린이집"
    if idx <= 6:
        return "elementary", f"초등학교 {idx}학년"
    if idx <= 9:
        return "middle", f"중학교 {idx - 6}학년"
    return "high", f"고등학교 {min(idx - 9, 3)}학년"


def age_ym(birth, test):
    months = (test.year - birth.year) * 12 + (test.month - birth.month)
    if test.day < birth.day:
        months -= 1
    return months // 12, months % 12


# --------------------------------------------------------------------------------------
# 프로파일 유형
# --------------------------------------------------------------------------------------
PROFILES = {
    # name: (factor multipliers, boosts(z), check fn key)
    "내재화형": ({"g": .5, "INT": 1.0}, {}, "INT"),
    "위축 우세형": ({"g": .4, "INT": .6}, {"withdrawn": .55}, "withdrawn"),
    "신체증상 우세형": ({"g": .3, "INT": .5}, {"somatic": .7}, "somatic"),
    "우울/불안 우세형": ({"g": .4, "INT": .7}, {"anxdep": .5}, "anxdep"),
    "주의집중 우세형": ({"g": .4, "ATT": 1.0}, {}, "attention"),
    "공격성(외현화)형": ({"g": .4, "EXT": 1.0, "ATT": .3}, {"aggressive": .3}, "EXT"),
    "비행형": ({"g": .4, "EXT": .7}, {"delinquent": .65}, "delinquent"),
    "사회적 미성숙형": ({"g": .4, "ATT": .3, "INT": .3}, {"socimm": .65}, "socimm"),
    "사고의 문제형": ({"g": .5}, {"thought": .75}, "thought"),
    "주의집중+내재화 혼합형": ({"g": .5, "ATT": .9, "INT": .8}, {}, "ATT+INT"),
    "혼합형(내재화+외현화)": ({"g": .6, "INT": .8, "EXT": .8, "ATT": .4}, {}, "INT+EXT"),
    "전반적 상승형": ({"g": 1.0, "INT": .6, "EXT": .6, "ATT": .6}, {}, "TOT"),
}


def profile_weights(sex, band, tier):
    w = {
        "내재화형": 8, "위축 우세형": 5, "신체증상 우세형": 3, "우울/불안 우세형": 6,
        "주의집중 우세형": 8, "공격성(외현화)형": 7, "비행형": 2, "사회적 미성숙형": 5,
        "사고의 문제형": 2, "주의집중+내재화 혼합형": 5, "혼합형(내재화+외현화)": 6, "전반적 상승형": 2,
    }
    if sex == "남":
        for k in ("주의집중 우세형", "공격성(외현화)형", "비행형"):
            w[k] *= 1.6
    else:
        for k in ("내재화형", "우울/불안 우세형", "신체증상 우세형"):
            w[k] *= 1.6
    if band == "preschool":
        w["비행형"] = 0
        w["신체증상 우세형"] *= .5
        w["사회적 미성숙형"] *= 1.4
        w["공격성(외현화)형"] *= 1.3
    if band in ("middle", "high"):
        w["비행형"] *= 3
        w["신체증상 우세형"] *= 2
        w["우울/불안 우세형"] *= 1.6
        w["위축 우세형"] *= 1.5
        w["사회적 미성숙형"] *= .4
    if tier == "심각":
        w["전반적 상승형"] *= 8
        w["혼합형(내재화+외현화)"] *= 3
    return list(w.items())


# --------------------------------------------------------------------------------------
# 텍스트 뱅크
# --------------------------------------------------------------------------------------
FINDING_BANK = {
    "withdrawn": {
        "준임상": ["혼자 지내려 하거나 소극적인 모습처럼 사회적 위축과 관련된 행동이 또래보다 많이 보고됨",
                 "새로운 활동이나 대인 상황에서 참여를 주저하는 모습이 상대적으로 많이 보고됨",
                 "말수가 적고 활동 반경이 좁아지는 등 위축 양상이 선별 기준을 넘어섬"],
        "임상": ["사회적 상호작용 회피, 무표정·무관심 등 위축 관련 행동이 또래 대비 뚜렷하게 상승",
               "위축 양상이 임상 기준을 초과하여 또래 관계와 일상 활동 참여 전반에 제한이 있을 가능성"],
    },
    "somatic": {
        "준임상": ["뚜렷한 신체적 원인 없이 두통·복통·피로감 등을 호소하는 빈도가 다소 높음",
                 "긴장 상황(등원·등교, 시험 등)과 신체 불편 호소가 연결될 가능성 고려"],
        "임상": ["반복적인 신체 불편 호소가 임상 수준으로 보고되어, 의학적 원인 확인과 함께 정서적 요인 탐색 필요",
               "신체증상으로 인한 결석·활동 회피 등 일상 기능 저하 가능성"],
    },
    "anxdep": {
        "준임상": ["걱정하거나 긴장하는 등 불안과 관련된 반응이 또래보다 많이 보고됨",
                 "낯선 상황에서 불안 반응이 커지는지 살펴볼 필요가 있음",
                 "기분이 쉽게 가라앉거나 자신감이 낮은 모습이 상대적으로 많이 보고됨"],
        "임상": ["불안·우울 관련 정서 반응이 임상 기준을 초과하여 정서적 고통 수준이 높은 것으로 판단됨",
               "자기 비하, 슬픔, 과도한 걱정 등이 일상 전반에서 지속적으로 나타날 가능성"],
    },
    "socimm": {
        "준임상": ["미성숙한 행동이나 의존적 양상이 나이에 비해 많이 보고됨",
                 "친구 관계를 만들고 이어 가는 데 어려움이 있는지 살펴볼 필요가 있음"],
        "임상": ["또래보다 어린 아이들과 어울리거나 놀림을 받는 등 사회적 미성숙 양상이 뚜렷함",
               "또래 집단 내 수용 경험 저하로 인한 2차적 정서 문제 가능성"],
    },
    "thought": {
        "준임상": ["특정 생각이나 행동을 반복하는 경향, 엉뚱한 행동 등 관련 문항이 다소 높게 보고됨",
                 "해당 행동이 나타나는 상황과 빈도에 대한 구체적 확인 필요"],
        "임상": ["반복적·강박적 행동이나 이해하기 어려운 생각·행동 관련 문항이 임상 수준으로 보고됨",
               "보호자 관찰 맥락의 구체적 확인과 전문가 면담을 통한 정밀 평가가 필요한 영역"],
    },
    "attention": {
        "준임상": ["과제 지속의 어려움, 산만함, 충동적 행동 등이 또래 대비 상승된 양상",
                 "학습 상황 및 규칙이 있는 활동에서 주의 깊은 관찰 요망"],
        "임상": ["집중 곤란, 과잉 활동, 충동성 관련 행동이 임상 기준을 초과하여 또래 대비 뚜렷하게 상승",
               "학업 수행과 또래·가정 내 규칙 준수 전반에 영향을 줄 가능성"],
    },
    "delinquent": {
        "준임상": ["거짓말, 규칙 위반 등 행동 문제가 또래 평균보다 다소 높게 보고됨",
                 "행동이 나타나는 상황(또래 영향, 감독 공백 등)에 대한 확인 필요"],
        "임상": ["규칙 위반·거짓말·무단 이탈 등 비행 관련 행동이 임상 수준으로 보고됨",
               "또래 영향과 생활 환경 요인을 포함한 다각적 평가가 필요한 영역"],
    },
    "aggressive": {
        "준임상": ["고집을 부리거나 짜증을 내고 말다툼을 하는 등 공격적 행동이 또래보다 많이 보고됨",
                 "좌절 상황에서의 감정 조절 어려움 가능성"],
        "임상": ["반항, 분노 폭발, 신체적·언어적 공격 행동이 임상 기준을 초과하여 보고됨",
               "가정 내 갈등 및 또래 관계 문제로 이어질 가능성이 높아 개입 방안 검토 필요"],
    },
    "emoinst": {
        "준임상": ["잘 울거나 감정이 급변하는 등 정서 조절 관련 행동이 또래 대비 상승",
                 "좌절·꾸중 상황에서의 감정 회복 속도에 대한 관찰 요망"],
        "임상": ["분노발작, 감정 급변, 잦은 울음 등 정서 불안정 양상이 임상 수준으로 보고됨",
               "정서 조절을 돕는 양육·환경적 지원 방안 검토 필요"],
    },
    "sexprob": {
        "준임상": ["성 관련 행동 문항 일부가 또래 대비 높게 보고되어, 발달 단계상 자연스러운 범위인지 전문가 확인 필요"],
        "임상": ["성 관련 행동 문항이 높게 보고되어 전문가 면담을 통한 맥락 확인 필요"],
    },
}

# 보호자 의견 뱅크: scale -> band -> [(text, tag, min_t)]
COMMENT_BANK = {
    "withdrawn": {
        "preschool": [("유치원에서 친구들이 놀자고 해도 혼자 블록만 가지고 논대요.", "기관에서 혼자 노는 모습", 0),
                      ("낯선 어른이 말을 걸면 제 뒤로 숨고 대답을 잘 안 해요.", "낯선 사람 앞 위축", 0),
                      ("놀이터에 가도 다른 아이들 노는 걸 구경만 하고 끼지를 않아요.", "또래 놀이 참여 저조", 0)],
        "elementary": [("쉬는 시간에도 자리에 혼자 앉아 있다고 선생님께 들었어요.", "학교에서 혼자 지냄", 0),
                       ("예전엔 좋아하던 태권도도 요즘은 가기 싫다고 해요.", "활동 흥미 저하", 0),
                       ("친구 생일파티에 초대받아도 안 가겠다고 해요.", "또래 모임 회피", 0)],
        "teen": [("학교 끝나면 방에 들어가서 저녁 먹을 때 말고는 안 나와요.", "방에만 머무름", 0),
                 ("친구 얘기를 물어보면 '없어'라고만 하고 대화를 피해요.", "대화 회피", 0),
                 ("주말에도 밖에 나가지 않고 하루 종일 누워만 있어요.", "외부 활동 감소", 0)],
    },
    "somatic": {
        "preschool": [("아침마다 배가 아프다고 해서 유치원을 늦게 가는 날이 많아요.", "등원 전 복통 호소", 0),
                      ("병원에서는 이상이 없다는데 자꾸 다리가 아프다고 해요.", "원인 불명 통증 호소", 0)],
        "elementary": [("월요일 아침만 되면 머리가 아프다, 배가 아프다고 해요.", "등교 전 신체 호소", 0),
                       ("소아과에서는 괜찮다는데 보건실에 자주 간다고 연락이 와요.", "보건실 잦은 방문", 0),
                       ("시험 전날이면 꼭 토할 것 같다고 해요.", "시험 전 신체 불편", 0)],
        "teen": [("두통 때문에 조퇴한 게 이번 학기에만 여러 번이에요.", "두통으로 인한 조퇴", 0),
                 ("늘 피곤하다고 하고 어지럽다는 말을 자주 해요. 검사해도 이상은 없대요.", "만성 피로·어지럼 호소", 0)],
    },
    "anxdep": {
        "preschool": [("엄마가 안 보이면 울면서 찾아다녀요. 잠깐 화장실 가는 것도 힘들어해요.", "분리 시 불안", 0),
                      ("작은 실수에도 '나는 못해'라며 울어버려요.", "실수에 대한 과민 반응", 0),
                      ("밤에 무서운 꿈을 꿨다며 자주 깨요.", "야간 불안", 0)],
        "elementary": [("작은 일에도 걱정이 많고, 잘못될까 봐 몇 번씩 물어봐요.", "과도한 걱정", 0),
                       ("'나는 잘하는 게 하나도 없어'라는 말을 자주 해요.", "자기 비하 표현", 0),
                       ("발표가 있는 날엔 전날부터 잠을 못 자요.", "수행 불안", 0)],
        "teen": [("요즘 부쩍 우울해 보이고 이유 없이 울 때가 있어요.", "우울감·울음", 0),
                 ("성적 얘기만 나오면 너무 예민해지고 불안해해요.", "성적 관련 불안", 0),
                 ("'사는 게 재미없다'는 말을 한 적이 있어서 걱정돼요.", "무기력감 표현", 70)],
    },
    "socimm": {
        "preschool": [("동생 같은 행동을 많이 해요. 아직 혼자 하려는 게 별로 없어요.", "의존적·어린 행동", 0),
                      ("또래보다 말이나 행동이 어리다는 얘기를 들어요.", "연령 대비 미성숙", 0)],
        "elementary": [("친구들 사이에 잘 끼지 못하는 것 같아요.", "또래 관계 어려움", 0),
                       ("자기보다 어린 동생들하고만 놀려고 해요.", "어린 아이들과 어울림", 0),
                       ("반 친구들이 놀린다고 울면서 온 적이 몇 번 있어요.", "또래 놀림 경험", 0)],
        "teen": [("친구들 사이에서 눈치가 없다는 말을 듣는 것 같아요.", "또래 관계 미숙", 0),
                 ("나이에 비해 엄마한테 너무 의존해요.", "의존적 태도", 0)],
    },
    "thought": {
        "preschool": [("같은 행동을 계속 반복하고, 멈추라고 하면 크게 울어요.", "반복 행동", 0),
                      ("혼자 중얼거리면서 노는 시간이 길어요.", "혼잣말 놀이", 0)],
        "elementary": [("손 씻기를 여러 번 반복하고, 물건 정리가 조금만 달라져도 못 견뎌해요.", "반복·정리 집착", 0),
                       ("가끔 엉뚱한 얘기를 해서 무슨 뜻인지 모를 때가 있어요.", "이해하기 어려운 말", 0)],
        "teen": [("문을 잠갔는지 몇 번씩 확인하러 다시 가요.", "반복 확인 행동", 0),
                 ("가끔 이상한 소리가 들린다고 하는데 장난인지 모르겠어요.", "특이 지각 호소", 70)],
    },
    "attention": {
        "preschool": [("한 가지 놀이를 오래 못 하고 계속 이것저것 옮겨 다녀요.", "놀이 지속 어려움", 0),
                      ("유치원 선생님이 앉아 있는 시간에 자꾸 돌아다닌다고 하세요.", "기관 내 착석 어려움", 0)],
        "elementary": [("집에서는 별일 없는데 학교에서는 수업 시간에 산만하다는 말을 자주 들어요.", "학교에서 산만함", 0),
                       ("숙제 하나 하는 데 몇 시간씩 걸리고 계속 딴짓을 해요.", "과제 수행 지연", 0),
                       ("준비물이나 알림장을 매일 잃어버려요.", "잦은 분실·건망", 0)],
        "teen": [("공부를 하려고 앉아도 10분을 못 버티고 휴대폰을 봐요.", "학습 집중 곤란", 0),
                 ("수행평가 마감을 자꾸 놓쳐서 선생님께 연락이 와요.", "과제 마감 누락", 0)],
    },
    "delinquent": {
        "preschool": [("친구 장난감을 몰래 가져온 적이 몇 번 있어요.", "타인 물건 가져옴", 0),
                      ("혼날까 봐 거짓말을 자주 해요.", "잦은 거짓말", 0)],
        "elementary": [("거짓말이 늘어서 어디까지 믿어야 할지 모르겠어요.", "거짓말 증가", 0),
                       ("엄마 지갑에서 돈을 꺼내 간 적이 있어요.", "돈을 몰래 가져감", 0)],
        "teen": [("귀가 시간을 자주 어기고 연락이 안 될 때가 있어요.", "귀가 시간 미준수", 0),
                 ("학교를 빠지고 친구들과 PC방에 있다가 연락받은 적이 있어요.", "무단 결석", 0),
                 ("어울리는 친구들이 바뀌고 나서 말을 안 듣기 시작했어요.", "또래 영향 변화", 0)],
    },
    "aggressive": {
        "preschool": [("원하는 대로 안 되면 바닥에 누워서 소리를 지르고 떼를 써요.", "분노 발작·떼쓰기", 0),
                      ("동생을 자주 때려서 매일 혼내게 돼요.", "형제 간 공격 행동", 0)],
        "elementary": [("화가 나면 물건을 던지고 문을 쾅 닫아요.", "분노 시 물건 던짐", 0),
                       ("친구랑 자주 싸워서 학교에서 연락이 와요.", "또래와 잦은 다툼", 0),
                       ("말대꾸가 심하고 하지 말라는 걸 더 해요.", "반항적 태도", 0)],
        "teen": [("조금만 말해도 짜증을 내고 대들어서 대화가 안 돼요.", "잦은 짜증·반항", 0),
                 ("화가 나면 욕을 하고 벽을 친 적도 있어요.", "분노 시 언어·신체 공격", 0)],
    },
    "emoinst": {
        "elementary": [("기분이 갑자기 좋았다가 나빠졌다가 해서 맞추기가 힘들어요.", "감정 기복", 0),
                       ("별일 아닌데도 잘 울고 한번 울면 오래 가요.", "잦은 울음", 0)],
    },
    "general": {
        "preschool": [("특별히 걱정되는 건 없는데, 또래만큼 잘 크고 있는지 확인하고 싶었어요.", "발달 확인 목적", 0),
                      ("동생이 태어나고 나서 떼가 조금 늘었는데 일시적인 건지 궁금해요.", "동생 출생 후 변화", 0),
                      ("어린이집에서 잘 지낸다고 들었어요. 그래도 한 번 점검해 보고 싶었어요.", "기관 적응 확인", 0)],
        "elementary": [("학교생활은 잘하고 있다고 들었어요. 그냥 객관적으로 한 번 확인해 보고 싶었어요.", "객관적 확인 목적", 0),
                       ("전학 후에 적응을 잘하고 있는지 궁금했어요.", "전학 후 적응 확인", 0),
                       ("가끔 고집을 부리지만 크게 문제라고 생각하지는 않아요.", "가벼운 고집", 0),
                       ("게임 시간 때문에 가끔 실랑이가 있는 정도예요.", "게임 시간 갈등", 0)],
        "teen": [("사춘기라 말수가 줄긴 했는데 이 정도는 괜찮은 건지 궁금해요.", "사춘기 변화 확인", 0),
                 ("학원 스케줄이 많아서 스트레스가 있지 않을까 해서요.", "학업 스트레스 우려", 0),
                 ("큰 문제는 없는데 요즘 잠드는 시간이 늦어진 게 조금 신경 쓰여요.", "수면 시간 지연", 0)],
    },
}

INT_KEYS = ["withdrawn", "somatic", "anxdep"]
EXT_KEYS = ["delinquent", "aggressive"]


def band_of(level):
    return "preschool" if level == "preschool" else ("elementary" if level == "elementary" else "teen")


def josa(word, kind):
    """kind: '이/가', '은/는', '와/과', '을/를'"""
    ch = word.rstrip(")").strip()[-1]
    code = ord(ch) - 0xAC00
    has_final = 0 <= code <= 11171 and (code % 28) != 0
    a, b = kind.split("/")
    return word + (a if has_final else b)


COMP_NAMES = {"internalizing": "내재화 문제", "externalizing": "외현화 문제", "total": "총 문제행동"}
COMP_DOMAIN = {
    "internalizing": "위축·신체증상·우울/불안 같은 정서 영역",
    "externalizing": "비행·공격성 같은 행동 영역",
    "total": "문제행동 전반",
}


# --------------------------------------------------------------------------------------
# 한 사례 생성
# --------------------------------------------------------------------------------------
def classify(rec):
    comps = rec["_comp_t"]
    syn = rec["_syn_t"]
    clin_syn = [k for k, t in syn.items() if t >= 70]
    if comps["total"] >= 70 and len(clin_syn) >= 2:
        return "심각"
    if any(t >= 63 for t in comps.values()) or clin_syn:
        return "임상"
    if any(t >= 60 for t in comps.values()) or any(t >= 60 for t in syn.values()):
        return "준임상"
    return "정상"


def profile_ok(profile, comps, syn):
    if profile == "정상":
        return True
    key = PROFILES[profile][2]
    if key == "INT":
        return comps["internalizing"] >= 60
    if key == "EXT":
        return comps["externalizing"] >= 60 or syn["aggressive"] >= 60
    if key == "ATT+INT":
        return syn["attention"] >= 60 and comps["internalizing"] >= 60
    if key == "INT+EXT":
        return comps["internalizing"] >= 60 and comps["externalizing"] >= 60
    if key == "TOT":
        return comps["total"] >= 63
    # 단일 척도형: 해당 척도가 가장 높은 척도 중 하나(최고점과 3점 이내)이며 60 이상
    top = max(syn.values())
    return syn[key] >= 60 and syn[key] >= top - 3


LEVEL_RANGE = {"정상": (0, 0), "준임상": (1.0, 2.0), "임상": (1.8, 2.9), "심각": (2.6, 3.8)}


def simulate_scores(rng, norms, group, profile, tier, age_band, emo_eligible, sex_eligible):
    mult, boosts, _ = PROFILES.get(profile, ({}, {}, None))
    lo, hi = LEVEL_RANGE[tier]
    level = rng.uniform(lo, hi)
    if tier == "정상":
        f = {k: rng.gauss(0, .55) for k in FACTORS}
    else:
        f = {k: rng.gauss(0, .5) + level * mult.get(k, 0) for k in FACTORS}
    raws = {}
    for k in list(SYN) + ["other"]:
        b = boosts.get(k, 0) * level
        raws[k] = raw_score(k, f, rng, group, b)
    raws["emoinst"] = raw_score("emoinst", f, rng, group) if emo_eligible else None
    if sex_eligible:
        # 성문제 척도는 문제행동 수준과 약하게만 연동
        raws["sexprob"] = raw_score("sexprob", {"g": f["g"] * .4}, rng, group)
    else:
        raws["sexprob"] = None
    nm = norms[group]
    syn_t = {k: nm[k].t_score(raws[k], True) for k in SYN}
    comp_raw = {
        "internalizing": raws["withdrawn"] + raws["somatic"] + raws["anxdep"],
        "externalizing": raws["delinquent"] + raws["aggressive"],
        "total": sum(raws[k] for k in SYN) + raws["other"],
    }
    comp_t = {
        "internalizing": nm["INT"].t_score(comp_raw["internalizing"], False),
        "externalizing": nm["EXT"].t_score(comp_raw["externalizing"], False),
        "total": nm["TOT"].t_score(comp_raw["total"], False),
    }
    emo_t = nm["emoinst"].t_score(raws["emoinst"], True) if raws["emoinst"] is not None else None
    sex_t = nm["sexprob"].t_score(raws["sexprob"], True) if raws["sexprob"] is not None else None
    return f, raws, syn_t, comp_raw, comp_t, emo_t, sex_t


def competence_scores(rng, f, school_eligible):
    g, i, a = f["g"], f["INT"], f["ATT"]
    soc = 50 + 10 * (-0.35 * g - 0.35 * i - 0.1 * a) + rng.gauss(0, 7)
    sch = 50 + 10 * (-0.3 * g - 0.45 * a - 0.1 * i) + rng.gauss(0, 7) if school_eligible else None
    act = 50 + 10 * (-0.3 * g - 0.2 * i) + rng.gauss(0, 8)
    parts = [soc, act] + ([sch] if sch is not None else [])
    tot = sum(parts) / len(parts) - 1.0 + rng.gauss(0, 2)

    def c(x):
        return None if x is None else int(round(max(20, min(65, x))))
    return c(soc), c(sch), c(tot)


def pick(rng, seq, k=1):
    seq = list(seq)
    rng.shuffle(seq)
    return seq[:k]


def make_record(rng, norms, idx, tier, used_names):
    # ---- 인적 정보
    while True:
        sex = rng.choice(["남", "여"])
        age_target = weighted(rng, [(a, w) for a, w in zip(range(4, 18),
                                [6, 7, 8, 9, 9, 9, 9, 8, 8, 7, 6, 6, 5, 4])])
        test = date(2026, 1, 5) + timedelta(days=rng.randint(0, 263))
        while test.weekday() >= 5:
            test += timedelta(days=1)
        birth = test - timedelta(days=int(age_target * 365.25 + rng.randint(0, 364)))
        y, m = age_ym(birth, test)
        if 4 <= y <= 17:
            break
    level, grade = school_info(birth, test)
    band = band_of(level)
    group = (sex, "4-11" if y <= 11 else "12-17")
    norm_label = f"{'남자' if sex == '남' else '여자'} {'4–11세' if y <= 11 else '12–17세'}"
    while True:
        name = rng.choice(SURNAMES) + rng.choice(GIVEN_M if sex == "남" else GIVEN_F)
        if name not in used_names:
            used_names.add(name)
            break

    emo_eligible = 6 <= y <= 11
    sex_eligible = 4 <= y <= 11
    emo_admin = emo_eligible and rng.random() < 0.55
    sex_admin = sex_eligible and rng.random() < 0.25
    comp_admin = rng.random() < 0.6
    school_eligible = level != "preschool"

    # ---- 점수 생성 (목표 등급·프로파일과 일치할 때까지 재추출)
    if tier == "정상":
        profile = "정상"
    else:
        profile = weighted(rng, profile_weights(sex, level, tier))
    for attempt in range(4000):
        if attempt and attempt % 400 == 0 and tier != "정상":
            profile = weighted(rng, profile_weights(sex, level, tier))
        f, raws, syn_t, comp_raw, comp_t, emo_t, sex_t = simulate_scores(
            rng, norms, group, profile, tier, level, emo_admin, sex_admin)
        rec_tmp = {"_comp_t": comp_t, "_syn_t": syn_t}
        if classify(rec_tmp) != tier or not profile_ok(profile, comp_t, syn_t):
            continue
        if sex_t is not None and sex_t >= 66:
            continue
        if tier == "정상" and emo_t is not None and emo_t >= 60:
            continue
        break
    else:
        raise RuntimeError("generation failed")

    if comp_admin:
        soc_t, sch_t, tot_t = competence_scores(rng, f, school_eligible)
    else:
        soc_t = sch_t = tot_t = None

    # ---- 구조화
    syndrome_list = []
    for key, ko, en, items, dom, _ in SYNDROMES:
        t = syn_t[key]
        syndrome_list.append({
            "key": key, "name_ko": ko, "name_en": en, "domain": dom, "items": items,
            "raw": raws[key], "max_raw": MAX_RAW[key], "t": t,
            "percentile": pct_num(t, True), "percentile_text": pct_text(t, True),
            "range": syndrome_range(t),
        })
    composites = {}
    for k in ("internalizing", "externalizing", "total"):
        t = comp_t[k]
        composites[k] = {
            "name_ko": COMP_NAMES[k], "raw": comp_raw[k], "t": t,
            "percentile": pct_num(t), "percentile_text": pct_text(t), "range": composite_range(t),
        }

    if comp_admin:
        social = {
            "administered": True,
            "sociability": {"t": soc_t, "range": competence_range(soc_t, False)},
            "school_performance": ({"t": sch_t, "range": competence_range(sch_t, False)}
                                   if sch_t is not None else None),
            "total_competence": {"t": tot_t, "range": competence_range(tot_t, True)},
            "note": ("학업수행 척도는 초등학생부터 적용하므로 이번 결과에는 없습니다."
                     if sch_t is None else None),
        }
    else:
        social = {
            "administered": False, "sociability": None, "school_performance": None, "total_competence": None,
            "note": ("미실시 · 사회능력 척도(사회성, 학업수행, 총 사회능력)는 이번 검사에 포함되지 않았습니다. "
                     + ("초등학생부터 적용하는 학업수행 척도는 그때 함께 실시할 수 있습니다."
                        if not school_eligible else "필요하면 이후에 따로 실시할 수 있습니다.")),
        }

    special = {
        "emotional_instability": {
            "eligible": emo_eligible, "administered": emo_admin,
            "raw": raws["emoinst"] if emo_admin else None,
            "t": emo_t if emo_admin else None,
            "range": syndrome_range(emo_t) if emo_admin else None,
            "note": ("정서불안정 척도(한국판에만 있는 특수척도, 6–11세 대상): 잘 울기, 분노발작, 감정이 갑자기 바뀌는 모습 등 10문항. "
                     + ("실시." if emo_admin else ("해당 연령군에 해당하나 미실시. 추후 실시를 권장합니다."
                                                if emo_eligible else "적용 연령(6–11세)이 아니어서 미적용.")))
        },
        "sex_problems": {
            "eligible": sex_eligible, "administered": sex_admin,
            "raw": raws["sexprob"] if sex_admin else None,
            "t": sex_t if sex_admin else None,
            "range": syndrome_range(sex_t) if sex_admin else None,
            "note": ("성문제 척도(4–11세): " + ("실시." if sex_admin else (
                "적용 연령이지만 필요할 때만 골라 실시하는 척도로, 이번 검사에서는 실시하지 않음."
                if sex_eligible else "적용 연령(4–11세)이 아니어서 미적용.")))
        },
    }

    # ---- 보호자 의견
    elevated = sorted([(syn_t[k], k) for k in SYN if syn_t[k] >= 60], reverse=True)
    comments = []
    used_tags = set()

    def add_comment(scale, maxn=1):
        bank = COMMENT_BANK.get(scale, {}).get(band, [])
        t = syn_t.get(scale, emo_t if scale == "emoinst" else 0) or 0
        cands = [c for c in bank if t >= c[2] and c[1] not in used_tags]
        for text, tag, _ in pick(rng, cands, maxn):
            comments.append({"text": text, "related_scale": scale if scale != "general" else None, "tag": tag})
            used_tags.add(tag)

    if tier == "정상":
        top_t, top_k = max((syn_t[k], k) for k in SYN)
        add_comment("general", 1)
        if top_t >= 56 and rng.random() < 0.5:
            add_comment(top_k, 1)
        elif rng.random() < 0.35:
            add_comment("general", 1)
    else:
        n_scales = 1 if tier == "준임상" else (2 if tier == "임상" else 3)
        targets = [k for _, k in elevated][:n_scales]
        if not targets:  # 종합지표만 상승한 경우: 해당 영역 최고 척도
            if comp_t["internalizing"] >= 60:
                targets = [max(INT_KEYS, key=lambda k: syn_t[k])]
            else:
                targets = [max(SYN, key=lambda k: syn_t[k])]
        for i, k in enumerate(targets):
            add_comment(k, 2 if (i == 0 and rng.random() < 0.35) else 1)
        if emo_admin and emo_t >= 60 and rng.random() < 0.6:
            add_comment("emoinst", 1)
    comment_by_scale = {}
    for c in comments:
        if c["related_scale"]:
            comment_by_scale.setdefault(c["related_scale"], c["tag"])
    risk_flags = [c["tag"] for c in comments if c["tag"] in ("무기력감 표현", "특이 지각 호소")]

    # ---- 주요 관찰 소견
    findings = []
    for k in ("internalizing", "externalizing", "total"):
        t = comp_t[k]
        r = composite_range(t)
        if r == "정상":
            continue
        pts = []
        if k == "internalizing":
            pts.append("내재화 문제가 선별 기준인 60T(85%tile)를 넘어, 걱정·위축 같은 정서 영역을 살펴볼 필요가 있음" if r == "준임상"
                       else f"내재화 문제가 임상 기준인 63T(90%tile)를 넘어({ptile(t)}) 걱정·위축 같은 정서 영역의 어려움이 또래보다 뚜렷하게 보고됨")
            subs = [SYN[s][1] for s in INT_KEYS if syn_t[s] >= 60]
        elif k == "externalizing":
            pts.append("외현화 문제가 선별 기준인 60T(85%tile)를 넘어, 규칙을 지키는 모습과 감정을 드러내는 방식을 살펴볼 필요가 있음" if r == "준임상"
                       else f"외현화 문제가 임상 기준인 63T(90%tile)를 넘어({ptile(t)}) 규칙 위반·공격 행동처럼 겉으로 드러나는 어려움이 또래보다 뚜렷하게 보고됨")
            subs = [SYN[s][1] for s in EXT_KEYS if syn_t[s] >= 60]
        else:
            pts.append("전체 문제행동 수준이 선별 기준(60T)을 넘어 여러 영역의 경미한 어려움이 누적된 양상" if r == "준임상"
                       else f"전체 문제행동 수준이 임상 기준(63T)을 초과, {ptile(t)}에 해당하여 다영역에 걸친 어려움이 시사됨")
            subs = None
        if subs is not None:
            if subs:
                pts.append(f"{'·'.join(subs)} 등 하위 척도가 함께 높게 나온 것이 종합지표에 더해짐")
            else:
                pts.append("개별 하위 척도는 모두 60T 미만이나 경미한 상승이 누적되어 종합지표가 상승함")
        findings.append({"title": f"{COMP_NAMES[k]} 종합 · T = {t}", "scale": k, "t": t,
                         "badge": f"종합지표 {r}", "points": pts})

    for t, k in elevated:
        r = syndrome_range(t)
        bank = FINDING_BANK[k][r]
        pts = []
        if r == "준임상" and t >= 65:
            pts.append(f"임상 기준인 70T에는 못 미치지만 {ptile(t, True)}에 해당하여 또래보다 높게 나타남")
        elif r == "임상":
            pts.append(f"임상 기준인 70T를 넘었으며 {ptile(t, True)}에 해당함")
        pts += pick(rng, bank, 1 if pts else 2)
        if k in comment_by_scale:
            pts.append(f"보호자 보고({comment_by_scale[k]})와 일치하는 양상")
        badge = "개별척도 준임상 (60–69T)" if r == "준임상" else "개별척도 임상 (≥70T)"
        findings.append({"title": f"{SYN[k][1]} · T = {t}", "scale": k, "t": t, "badge": badge, "points": pts})

    for skey, sname, tval in (("emoinst", "정서불안정(특수척도)", emo_t if emo_admin else None),
                              ("sexprob", "성문제(특수척도)", sex_t if sex_admin else None)):
        if tval is not None and tval >= 60:
            r = syndrome_range(tval)
            pts = pick(rng, FINDING_BANK[skey][r], 1)
            if skey in comment_by_scale:
                pts.append(f"보호자 보고({comment_by_scale[skey]})와 일치하는 양상")
            findings.append({"title": f"{sname} · T = {tval}", "scale": skey, "t": tval,
                             "badge": f"특수척도 {r}", "points": pts})

    if comp_admin:
        if social["total_competence"]["range"] != "정상":
            r = social["total_competence"]["range"]
            findings.append({
                "title": f"총 사회능력 · T = {tot_t}", "scale": "total_competence", "t": tot_t,
                "badge": "사회능력 임상 (≤33T)" if r == "임상" else "사회능력 준임상 (34–40T, 가정 기준)",
                "points": ["친구 관계, 활동 참여, 학업 수행 등 적응 자원이 또래 대비 낮게 보고됨",
                           "문제행동 감소와 함께 강점·자원 강화 측면의 접근 필요"]})
        for sk, nm_, txt in (("sociability", "사회성", "친구 수·또래 접촉 빈도 등 사회적 관계 지표가 낮게 보고됨"),
                             ("school_performance", "학업수행", "학업 수행 관련 보고가 또래 대비 낮아 학습 지원 필요성 검토")):
            v = social[sk]
            if v and v["range"] == "임상":
                findings.append({"title": f"{nm_} · T = {v['t']}", "scale": sk, "t": v["t"],
                                 "badge": "사회능력 하위 임상 (≤30T)", "points": [txt]})

    if not findings:
        top_t, top_k = max((syn_t[k], k) for k in SYN)
        pts = ["내재화·외현화·총 문제행동 및 8개 증후군 척도가 모두 정상 범위(60T 미만)",
               f"상대적으로 가장 높은 척도는 {SYN[top_k][1]}(T={top_t})이나 연령 평균 범위 내에 위치"]
        if top_t >= 56 and top_k in comment_by_scale:
            pts.append(f"보호자 보고({comment_by_scale[top_k]})는 일상적 관찰 수준으로 판단됨")
        findings.append({"title": "전반적 프로파일 · 정상 범위", "scale": None, "t": None,
                         "badge": "특이 소견 없음", "points": pts})

    # ---- 종합지표 요약 문장 (보고서 Ⅱ 하단)
    normal_c = [k for k in ("total", "externalizing", "internalizing") if composite_range(comp_t[k]) == "정상"]
    elev_c = [k for k in ("internalizing", "externalizing", "total") if composite_range(comp_t[k]) != "정상"]
    if not elev_c:
        comp_summary = "내재화, 외현화, 총 문제행동이 모두 정상 범위로 연령 평균 수준입니다."
    else:
        parts = []
        if normal_c:
            names = [COMP_NAMES[k] for k in normal_c]
            parts.append(f"{', '.join(names)} 수준은 정상 범위입니다.")
        sents = []
        for k in elev_c:
            t = comp_t[k]
            if composite_range(t) == "준임상":
                sents.append(f"{josa(COMP_NAMES[k], '은/는')} T={t}{ro(t)} 60–62T 구간인 준임상 범위에 속하므로, "
                             f"{josa(COMP_DOMAIN[k], '을/를')} 관찰해 볼 필요가 있습니다.")
            else:
                sents.append(f"{josa(COMP_NAMES[k], '은/는')} T={t}{ro(t)} 63T 이상인 임상 범위에 속하므로, "
                             f"{COMP_DOMAIN[k]}에 대해 전문가 평가를 받아 보기를 권합니다.")
        for i in range(1, len(sents)):
            sents[i] = ("또한 " if i == 1 else "아울러 ") + sents[i]
        if normal_c:
            sents[0] = "다만 " + sents[0]
        comp_summary = " ".join(parts + sents)

    # ---- 종합 해석
    subj = "본 아동" if y <= 11 else "본 청소년"

    def nt(k, kind):
        return f"{COMP_NAMES[k]}(T={comp_t[k]})" + josa(COMP_NAMES[k], kind)[len(COMP_NAMES[k]):]

    order = ("total", "internalizing", "externalizing")
    nn = [k for k in order if composite_range(comp_t[k]) == "정상"]
    bb = [k for k in order if composite_range(comp_t[k]) == "준임상"]
    cc = [k for k in order if composite_range(comp_t[k]) == "임상"]
    p1 = []
    if len(nn) == 3:
        p1.append(f"K-CBCL 규준으로 볼 때 {subj}의 총 문제행동(T={comp_t['total']}), 내재화 문제(T={comp_t['internalizing']}), "
                  f"외현화 문제(T={comp_t['externalizing']})는 모두 정상 범위로, 행동·정서 전반이 또래 평균 범위에 있습니다.")
    elif nn:
        names = [f"{COMP_NAMES[k]}(T={comp_t[k]})" for k in nn]
        joined = " 및 ".join(names)
        last = COMP_NAMES[nn[-1]]
        particle = josa(last, "이/가")[len(last):]
        if "externalizing" in nn and "internalizing" not in nn:
            tail = "비행·공격성 같은 행동 영역의 어려움은 또래와 비교해 두드러지지 않습니다."
        elif "internalizing" in nn and "externalizing" not in nn:
            tail = "위축·우울/불안 같은 정서 영역의 어려움은 또래와 비교해 두드러지지 않습니다."
        else:
            tail = "전반적인 문제행동의 양은 평균 범위에 있습니다."
        p1.append(f"K-CBCL 규준으로 볼 때 {subj}의 {joined}{particle} 정상 범위여서 {tail}")
    else:
        p1.append(f"K-CBCL 규준으로 볼 때 {subj}의 내재화·외현화·총 문제행동 종합지표는 모두 선별 기준인 60T를 넘었습니다.")
    for k in bb:
        p1.append(f"{nt(k, '은/는')} 60–62T 구간인 준임상 범위에 속하므로 {josa(COMP_DOMAIN[k], '을/를')} 관찰해 볼 필요가 있습니다.")
    endings = ["또래 대비 유의미하게 높은 수준입니다.", "또래 규준에 비해 뚜렷하게 상승되어 있습니다.",
               "임상적 주의가 필요한 수준으로 보고되었습니다."]
    for i, k in enumerate(cc):
        dom = COMP_DOMAIN[k]
        p1.append(f"{COMP_NAMES[k]}(T={comp_t[k]}, {ptile(comp_t[k])}){josa(COMP_NAMES[k], '은/는')[len(COMP_NAMES[k]):]} "
                  f"63T 이상인 임상 범위에 속해 {josa(dom, '이/가')} {endings[i % 3]}")
    if nn and (bb or cc):
        p1[1] = "한편 " + p1[1]
    para1 = " ".join(p1)

    p2 = []
    clin = [(t, k) for t, k in elevated if t >= 70]
    bord = [(t, k) for t, k in elevated if t < 70]

    def lst(items):
        out = []
        for t, k in items:
            if t >= 65:
                out.append(f"{SYN[k][1]} T={t}({ptile(t, True)})")
            else:
                out.append(f"{SYN[k][1]} T={t}")
        return ", ".join(out)

    if not elevated:
        top_t, top_k = max((syn_t[k], k) for k in SYN)
        if any(composite_range(comp_t[k]) != "정상" for k in comp_t):
            p2.append("개별 증후군 척도는 모두 60T 미만이나, 여러 하위 척도의 경미한 상승이 누적되어 종합지표가 상승한 양상입니다.")
        else:
            p2.append(f"개별 증후군 척도도 모두 정상 범위(60T 미만)이며, 상대적으로 가장 높은 {SYN[top_k][1]}(T={top_t}) 역시 "
                      f"연령 평균 범위 내에 있습니다.")
    else:
        if clin:
            lastname = SYN[clin[-1][1]][1]
            particle = josa(lastname, "이/가")[len(lastname):]
            s = f"증후군 척도 가운데 {lst(clin)}{particle} 임상 기준인 70T를 넘었고"
            if bord:
                s += f", {lst(bord)} {'등 ' + str(len(bord)) + '개 영역' if len(bord) > 1 else '영역'}도 60–69T 구간인 준임상 수준으로 함께 높게 나타났습니다."
            else:
                s += ", 그 밖의 증후군 척도는 정상 범위입니다."
        else:
            s = (f"증후군 척도 가운데 임상 기준인 70T를 넘은 척도는 없지만, {lst(bord)} "
                 f"{'등 ' + str(len(bord)) + '개 영역' if len(bord) > 1 else '영역'}이 60–69T 구간인 준임상 수준으로 높게 나타났습니다.")
        p2.append(s)
        ek = {k for _, k in elevated}
        combos = []
        if {"attention", "aggressive"} <= ek:
            combos.append("주의집중 문제와 공격성이 함께 상승한 양상은 충동 조절의 어려움이 규칙 준수나 또래 갈등으로 이어질 수 있음을 시사합니다.")
        if {"anxdep", "withdrawn"} <= ek:
            combos.append("우울/불안과 위축이 함께 상승하여, 정서적 어려움이 대인관계 회피의 형태로 나타나고 있을 가능성이 있습니다.")
        if {"anxdep", "somatic"} <= ek:
            combos.append("우울/불안과 신체증상의 동반 상승은 정서적 긴장이 신체 불편 호소로 표현되고 있을 가능성을 시사합니다.")
        if {"delinquent", "aggressive"} <= ek:
            combos.append("비행과 공격성이 동반 상승하여 규칙 위반 행동이 가정 밖 환경으로 확대될 가능성에 대한 관찰이 필요합니다.")
        if "socimm" in ek and ({"withdrawn", "attention"} & ek):
            other = "위축" if "withdrawn" in ek else "주의집중 문제"
            combos.append(f"사회적 미성숙이 {josa(other, '과/와')} 함께 높게 나와, 친구 관계의 어려움이 더 커질 가능성이 있습니다.")
        if "attention" in ek and comp_t["internalizing"] >= 60 and not combos:
            combos.append("주의집중 문제와 내재화 영역이 함께 높게 나와, 공부나 친구 관계에서 기능 저하가 생길 수 있는 취약 요인으로 볼 수 있습니다.")
        if comp_t["internalizing"] >= 60 and comp_t["externalizing"] >= 60:
            combos.append("내재화와 외현화 문제가 동시에 상승한 혼합 양상으로, 겉으로 드러나는 행동 문제 이면의 정서적 어려움을 함께 고려할 필요가 있습니다.")
        p2 += combos[:2]
        linked = [(k, comment_by_scale[k]) for _, k in elevated if k in comment_by_scale]
        if linked:
            k, tag = linked[0]
            p2.append(f"특히 {SYN[k][1]} 영역의 상승은 보호자의 \"{tag}\" 보고와 일치합니다.")
    if emo_admin:
        r = syndrome_range(emo_t)
        p2.append(f"한국판 특수척도인 정서불안정 척도는 T={emo_t}{ro(emo_t)} "
                  + ("정상 범위입니다." if r == "정상" else f"{r} 범위에 해당하여 감정 조절에 대한 관찰이 필요합니다."))
    if comp_admin:
        r = social["total_competence"]["range"]
        if r == "정상":
            p2.append(f"사회능력 척도는 총 사회능력 T={tot_t}{ro(tot_t)} 정상 범위에 있어 기본적인 사회·활동 적응 자원은 유지되고 있습니다.")
        else:
            p2.append(f"사회능력 척도에서는 총 사회능력이 T={tot_t}{ro(tot_t)} {r} 범위에 해당하여, 문제행동과 함께 적응 자원의 부족도 고려할 필요가 있습니다.")
    para2 = " ".join(p2)

    if level == "preschool":
        timing = "유아기는 발달 속도와 환경에 따라 행동 변화의 폭이 큰 시기이므로"
        others = "기관 교사의 관찰 정보"
    elif level == "elementary" and grade in ("초등학교 1학년", "초등학교 2학년"):
        timing = "학령 초기 적응이 이루어지는 시기이므로"
        others = "담임 교사가 답하는 교사용 TRF"
    elif grade == "초등학교 6학년" or grade == "중학교 1학년":
        timing = "중학교 진학 전후의 전환 시점이므로"
        others = "교사용 TRF 및 자기보고형 YSR"
    elif level == "high":
        timing = "학업 부담과 진로 관련 스트레스가 커지는 시기이므로"
        others = "자기보고형 YSR 및 교사 보고"
    else:
        timing = "학년이 바뀌는 것 같은 발달적 전이 시기에는 결과가 달라질 수 있으므로"
        others = "교사용 TRF" + (" 및 자기보고형 YSR" if y >= 11 else "")

    if tier == "정상":
        para3 = (f"현재 결과는 연령 평균 범위의 적응 상태를 보여 별도의 임상적 개입이 요구되지 않습니다. "
                 f"{timing} 일상적인 관찰을 유지하고, 보호자가 우려하는 행동이 지속되거나 새롭게 나타날 경우 재평가를 고려할 수 있습니다.")
        follow = ["일상적 관찰 유지", "우려 행동 지속 시 재평가 고려"]
    elif tier == "준임상":
        para3 = (f"지금 결과만으로 바로 임상 개입이 필요하다고 보기는 어렵지만, 선별 기준을 넘은 영역이 있어 "
                 f"그 영역을 지켜볼 필요가 있습니다. {timing} 3–6개월 간격으로 다시 평가해 변화를 확인하는 것이 권장되며, "
                 f"상담을 통해 가정·기관에서의 구체적 행동 양상을 함께 확인하는 것이 도움이 됩니다.")
        follow = ["상담을 통한 행동 양상 확인", "3–6개월 후 재평가", f"{others} 병행 고려"]
    elif tier == "임상":
        para3 = (f"임상 범위의 상승이 확인되어 전문가 상담을 통한 면밀한 평가가 권장됩니다. 보호자 보고만으로는 상황별 차이를 "
                 f"충분히 반영하기 어려우므로 {others} 등 다면적 정보를 함께 수집하여 문제의 범위와 지속성을 확인할 필요가 있습니다. "
                 f"{timing} 상담 결과에 따라 적절한 지원 방안을 조기에 마련하는 것이 바람직합니다.")
        follow = ["전문가 상담을 통한 정밀 평가", f"{others} 병행", "평가 결과에 따른 지원 계획 수립"]
    else:
        para3 = (f"여러 영역에서 임상 수준의 상승이 동시에 나타나 가정·학교 등 일상 기능 전반에 영향이 있을 가능성이 높습니다. "
                 f"가능한 한 빠른 시일 내에 아동·청소년 정신건강 전문가의 종합 평가(면담, 행동 관찰, {others} 등)를 받는 것이 권장되며, "
                 f"평가 결과에 따라 가정과 기관이 함께 참여하는 체계적인 지원이 필요할 수 있습니다.")
        follow = ["신속한 전문가 종합 평가", f"{others} 병행", "가정·기관 연계 지원 계획"]
    if risk_flags:
        para3 += (" 또한 보호자 의견 중 정서·지각 상태와 관련된 표현이 있어, 상담 시 현재 정서 상태와 안전 여부를 우선적으로 확인하는 것이 권장됩니다.")
        follow.insert(0, "상담 시 정서 상태 및 안전 여부 우선 확인")

    interp = "\n\n".join([para1, para2, para3])

    if tier == "정상":
        referral = comments[0]["tag"] if comments else "발달 상태 점검"
    else:
        referral = ", ".join(c["tag"] for c in comments[:2])

    overall_label = {"정상": "정상 범위", "준임상": "준임상(관찰 요망)", "임상": "임상(전문 평가 권장)",
                     "심각": "임상·다영역(신속한 전문 평가 권장)"}[tier]

    rec = {
        "id": f"KCBCL-SAMPLE-{idx:03d}",
        "report_type": "K-CBCL 보호자 보고형 (만 4–17세)",
        "child": {
            "name": name, "sex": sex, "birth_date": birth.isoformat(),
            "age_years": y, "age_months": m, "age_text": f"만 {y}세 {m}개월",
            "school_level": level, "grade": grade,
        },
        "informant": weighted(rng, INFORMANTS),
        "test_date": test.isoformat(),
        "norm_group": norm_label,
        "referral_reason": referral,
        "social_competence": social,
        "composite_scales": composites,
        "composite_summary": comp_summary,
        "syndrome_scales": syndrome_list,
        "special_scales": special,
        "key_findings": findings,
        "overall_interpretation": interp,
        "guardian_comments": comments,
        "recommended_follow_up": follow,
        "summary_flags": {
            "overall_level": overall_label,
            "elevated_composites": [k for k in comp_t if comp_t[k] >= 60],
            "borderline_syndromes": [k for t, k in elevated if t < 70],
            "clinical_syndromes": [k for t, k in elevated if t >= 70],
            "highest_syndrome": max(SYN, key=lambda k: syn_t[k]),
            "risk_expression_in_comments": bool(risk_flags),
        },
        "sample_meta": {"severity_tier": tier, "profile_type": profile},
    }
    return rec


def main():
    rng = random.Random(SEED)
    norms = build_norms(rng)
    tiers = ["정상"] * 30 + ["준임상"] * 28 + ["임상"] * 27 + ["심각"] * 15
    rng.shuffle(tiers)
    used = set()
    samples = [make_record(rng, norms, i + 1, t, used) for i, t in enumerate(tiers)]
    samples.sort(key=lambda r: r["test_date"])
    for i, r in enumerate(samples, 1):
        r["id"] = f"KCBCL-SAMPLE-{i:03d}"

    meta = {
        "title": "K-CBCL 검사 결과 가상 샘플 데이터셋",
        "version": "1.0",
        "generated_at": "2026-10-02",
        "count": len(samples),
        "random_seed": SEED,
        "purpose": "보호자용 결과 설명 AI PoC 개발·테스트용 가상 데이터",
        "disclaimer": [
            "모든 인적 정보(이름, 생년월일 등)는 무작위로 조합한 가상 정보입니다.",
            "원점수→T점수 변환은 실제 K-CBCL 규준표가 아니라 잠재요인 모델로 생성한 시뮬레이션 규준을 사용했습니다. "
            "척도 간 상관, 종합척도-하위척도 합산 관계, 판정 기준은 일관되게 유지되지만 실제 규준의 원점수-T점수 대응과는 다릅니다.",
            "실제 임상 판단이나 연구 목적으로 사용할 수 없습니다.",
        ],
        "reference_structure": "AI개발자_테스트자료_CBCL보고서 (K-CBCL 검사 결과 보고서 샘플)",
        "interpretation_criteria": {
            "t_score": "연령·성별 규준에 따른 T점수 (평균 50, 표준편차 10)",
            "composite_scales": {"정상": "T < 60", "준임상": "T 60–62", "임상": "T ≥ 63"},
            "syndrome_scales": {"정상": "T < 60", "준임상": "T 60–69", "임상": "T ≥ 70",
                                "note": "증후군 척도 T점수 하한은 50 (백분위 50 이하는 50T로 표기)"},
            "special_scales": "증후군 척도와 동일 기준 적용 (가정)",
            "social_competence": {"임상": "총 사회능력 33T 이하, 하위 척도 30T 이하 (가정 기준)",
                                  "준임상": "총점 34–40T, 하위척도 31–35T (ASEBA 관례를 참고한 가정)",
                                  "note": "사회능력 척도는 점수가 낮을수록 적응 자원이 부족함을 의미"},
            "percentile": "정규분포 기준 T점수 환산 백분위 (60T≈84, 63T≈90, 70T≈98)",
        },
        "scales": {
            "syndromes": [{"key": k, "name_ko": ko, "name_en": en, "items": it, "domain": d}
                          for k, ko, en, it, d, _ in SYNDROMES],
            "composites": {
                "internalizing": "위축 + 신체증상 + 우울/불안",
                "externalizing": "비행 + 공격성",
                "total": f"전체 117문항 (8개 증후군 {117 - OTHER_ITEMS}문항 + 기타 문제 {OTHER_ITEMS}문항)",
            },
            "special": {
                "emotional_instability": "정서불안정 (6–11세, 한국판 고유, 10문항)",
                "sex_problems": "성문제 (4–11세, 선택 적용)",
            },
            "social_competence": "사회성, 학업수행(초등학생 이상), 총 사회능력",
        },
        "norm_groups": ["남자 4–11세", "남자 12–17세", "여자 4–11세", "여자 12–17세"],
        "severity_tier_definition": {
            "정상": "모든 종합척도·증후군 척도 T < 60",
            "준임상": "종합척도 60–62T 또는 증후군 60–69T가 1개 이상, 임상 범위 없음",
            "임상": "종합척도 ≥ 63T 또는 증후군 ≥ 70T가 1개 이상",
            "심각": "총 문제행동 ≥ 70T 이면서 임상 범위 증후군 2개 이상 (데이터셋 구분용 라벨, K-CBCL 공식 용어 아님)",
        },
        "report_cautions": [
            "K-CBCL은 양육자 보고로 만든 선별 도구입니다. 이 결과 하나만으로 진단을 정하지 않습니다.",
            "답하는 사람이 아이를 어떤 상황에서 보는지에 따라 결과가 달라지기도 합니다. 그래서 교사용 TRF나 자기보고형 YSR을 함께 실시해 다면적 정보를 얻는 것을 권합니다.",
            "이 보고서의 임상 기준은 종합척도가 63T, 증후군 척도가 70T입니다. 60T부터는 준임상 범위로 보고 추가 검사나 관찰을 고려합니다.",
            "전문가가 진단을 위해 볼 때는 70T(98%tile)를, 살펴볼 아이를 넓게 찾을 때는 60T(85%tile)를 기준으로 삼기도 합니다.",
        ],
        "field_guide": {
            "composite_summary": "보고서 Ⅱ(문제행동 종합 지표) 하단 요약 문장",
            "key_findings": "보고서 Ⅴ(주요 관찰 소견) — 종합지표·증후군·특수척도·사회능력의 상승 항목",
            "overall_interpretation": "보고서 Ⅵ(종합 해석) — 3개 문단(종합지표 / 증후군·패턴 / 권고)",
            "guardian_comments": "보고서 Ⅶ(보호자 참고 의견) — related_scale: 연관 척도, tag: 요약 키워드",
            "sample_meta": "데이터셋 설계용 정보(목표 심각도, 생성 프로파일). 실제 보고서에는 표시되지 않음",
        },
    }
    # 공개 범위: 100건을 만들되(점수 재현성) 평가 샘플 10건만 내보낸다 (specs/poc.md 2-3-1, 2026-10-06)
    samples = [r for r in samples if r["id"].rsplit("-", 1)[1] in PUBLISHED]
    meta["count"] = len(samples)
    meta["generated_count"] = 100
    out = {"metadata": meta, "samples": samples}
    with open("kcbcl_samples.json", "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)
    print("written", len(samples))


if __name__ == "__main__":
    main()
