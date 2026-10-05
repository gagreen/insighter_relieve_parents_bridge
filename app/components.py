"""데모 화면용 순수 함수 (specs/poc.md 5장, PoC1-06).

기준선 값은 결과 view model의 thresholds(= 판정 기준 정의)에서만 읽는다(G-02). 검사 종류별 분기 없음(G-12).
"""
from html import escape

ZONE_COLORS = {"normal": "#e3efe3", "borderline": "#fbeccb", "clinical": "#f5d5d5"}
T_MIN, T_MAX = 20, 100
WIDTH, HEIGHT, PAD = 360, 46, 8
BAR_Y, BAR_H = 18, 12
MIN_LABEL_PX = 70   # 구간이 이보다 좁으면 이름은 툴팁(title)으로만 둔다


def _x(t: float) -> float:
    t = min(max(t, T_MIN), T_MAX)
    return PAD + (t - T_MIN) / (T_MAX - T_MIN) * (WIDTH - 2 * PAD)


def _zones(item: dict) -> list[tuple[float, float, str]]:
    th = {t["range"]: t["value"] for t in item["thresholds"]}
    if item["direction"] == "lower_is_worse":
        return [(T_MIN, th["clinical"], "clinical"), (th["clinical"], th["borderline"], "borderline"),
                (th["borderline"], T_MAX, "normal")]
    return [(T_MIN, th["borderline"], "normal"), (th["borderline"], th["clinical"], "borderline"),
            (th["clinical"], T_MAX, "clinical")]


def baseline_svg(item: dict, range_labels: dict[str, str]) -> str:
    """척도 1개의 가로 막대: 구간(판정 기준이 있을 때) + 기준선 + T점수 위치. 미실시는 위치 표시 없음."""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
             f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(item["name"])} 기준선 그래프">']
    if item["thresholds"]:
        for lo, hi, rng in _zones(item):
            x0, x1 = _x(lo), _x(hi)
            label = escape(range_labels[rng])
            parts.append(f'<rect x="{x0:.1f}" y="{BAR_Y}" width="{x1 - x0:.1f}" height="{BAR_H}" '
                         f'fill="{ZONE_COLORS[rng]}"><title>{label}</title></rect>')
            if x1 - x0 >= MIN_LABEL_PX:
                parts.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{BAR_Y + BAR_H + 12}" font-size="10" '
                             f'text-anchor="middle" fill="#555">{label}</text>')
        for th in item["thresholds"]:
            x = _x(th["value"])
            parts.append(f'<line data-threshold="{th["value"]}" x1="{x:.1f}" y1="{BAR_Y - 3}" x2="{x:.1f}" '
                         f'y2="{BAR_Y + BAR_H + 3}" stroke="#888" stroke-width="1">'
                         f'<title>{th["value"]} · {escape(th["label"])}</title></line>')
            parts.append(f'<text x="{x:.1f}" y="{BAR_Y - 5}" font-size="9" text-anchor="middle" fill="#777">'
                         f'{th["value"]}</text>')
    else:
        parts.append(f'<rect x="{PAD}" y="{BAR_Y}" width="{WIDTH - 2 * PAD}" height="{BAR_H}" fill="#eeeeee"/>')
    if item["t"] is not None:
        x = _x(item["t"])
        parts.append(f'<circle data-t="{item["t"]}" cx="{x:.1f}" cy="{BAR_Y + BAR_H / 2}" r="5" fill="#333">'
                     f'<title>T {item["t"]}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)
