"""PoC1-01 범위 판정 [G-02, G-12].

기준값은 assessment_types.definition(specs/poc.md 2-2)에서만 읽는다. 검사 종류별 분기 없음.
"""
NORMAL = "normal"
BORDERLINE = "borderline"
CLINICAL = "clinical"
NOT_ADMINISTERED = "not_administered"


def judge(scale: str, t: int | None, definition: dict) -> str | None:
    """T점수의 범위를 판정한다.

    - t가 None이면 정의 유무와 관계없이 not_administered (8-2 미실시).
    - scale이 definition["scales"]에 없으면 판정하지 않고 None (2-2, B-2 대조 제외).
    """
    if t is None:
        return NOT_ADMINISTERED
    scale_def = definition["scales"].get(scale)
    if scale_def is None:
        return None
    group = definition["groups"][scale_def["group"]]
    direction = group["direction"]
    if direction == "higher_is_worse":
        if t >= group["clinical_min"]:
            return CLINICAL
        if t >= group["borderline_min"]:
            return BORDERLINE
        return NORMAL
    if direction == "lower_is_worse":
        if t <= group["clinical_max"]:
            return CLINICAL
        if t <= group["borderline_max"]:
            return BORDERLINE
        return NORMAL
    raise ValueError(f"알 수 없는 direction: {direction!r} (scale={scale})")
