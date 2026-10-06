# data/

가상 K-CBCL 검사 결과 샘플. 모두 가상 데이터이며 실제 임상·연구에 쓸 수 없다.

| 경로 | 내용 | 만드는 방법 |
| --- | --- | --- |
| `kcbcl_samples.json` | 원천 데이터 10건 (공통 뼈대 아님, 손으로 고치지 않음) | `cd data && python ../scripts/generate_kcbcl_samples.py` (seed 20261002) |
| `kcbcl_results/<번호>.json` | 검사 결과 1건 = 파일 1개, 10건 (`CLAUDE.md` 8-1 공통 뼈대) | `python scripts/convert_kcbcl_to_skeleton.py` |
| `assessment_types/KCBCL_4_17.json` | `assessment_types` 시드 1행 (판정 기준 정의, `specs/poc.md` 2-2 형식) | 위 변환 스크립트가 함께 생성 |

payload의 JSON Schema: `schemas/kcbcl_4_17.schema.json`

공개 범위(2026-10-06, `specs/poc.md` 2-3-1): 생성 스크립트는 같은 seed로 100건을 만들고 평가에 쓰는 10건(`001 003 005 006 008 011 016 023 035 065`, 기준 샘플 035 + 다샘플 평가 샘플)만 내보낸다. 번호와 점수는 100건 기준 그대로다. 서술 문형은 자체 문장이다(과제로 받은 보고서 문장을 옮기지 않음).

## 결과 파일 1건의 구조

```
{
  "result_id", "child_id", "assessment_code", "administered_at", "schema_version",  ← assessment_results 컬럼
  "subject":     { child_id, name, sex, birth_date, school_level, grade },            ← 식별 정보(가상). subjects 테이블에만 적재, 마스킹 전용. 프롬프트·화면 요약 금지(G-09)
  "payload":     { assessment, schema_version, scores[], findings[], files[] },      ← 공통 뼈대
  "sample_meta": { synthetic, source_id, severity_tier, profile_type, referral_reason, expected_flags }  ← 테스트용 기대값. 적재·AI 근거에 쓰지 않음
}
```

## payload 규칙

- `scores[]`: `id`, `scale`, `name`, `t`, `percentile`(null 허용), `range`, `extra`
  - `scale`은 원천 데이터 키를 그대로 쓴다. 종합척도·증후군 척도 키는 `assessment_types/KCBCL_4_17.json`의 `definition.scales` 키와 같다.
  - `range`는 원보고서 라벨(정상/준임상/임상)을 `normal | borderline | clinical`로 옮긴 값이고, 미실시·적용 연령 아님은 `not_administered`(`t: null`)다. 규칙 엔진의 판정과 대조하는 기준(B-2)으로 쓴다.
  - 특수척도(`emotional_instability`, `sex_problems`)와 사회능력(`sociability`, `school_performance`, `total_competence`)은 판정 기준이 가정값이라 `definition.scales`에 `group` 없이 `direction`만 있다(백분위 문장 방향용). 이 항목의 `range`는 원보고서 라벨 그대로이며, 규칙 엔진은 판정하지 않고 B-2 대조에서 제외한다(`specs/poc.md` 2-2).
  - `percentile`은 정수(1–99). 99.5 초과는 99, 증후군·특수척도의 하한 50T는 null. 원래 표기는 `extra.percentile_text`(">99", "≤50").
- `findings[]`: `id`, `type`, `section`, `scale`(null 허용), `text`, `extra`. `text`는 원천 데이터(가상 보고서) 문장 그대로다.
  - `type`: `info` · `note` · `narrative` · `observation` · `recommendation` · `guardian_comment` · `caution`
- `files[]`: 샘플에 대응하는 PDF가 없어 빈 배열.
- id 접두어: `H` 기본 정보, `I`~`VII` 보고서 섹션(Ⅰ 사회능력, Ⅱ 종합지표, Ⅲ 증후군, Ⅳ 특수척도, Ⅴ 주요 관찰 소견, Ⅵ 종합 해석, Ⅶ 보호자 의견), `C` 해석 시 유의사항.

## 주의

- T점수는 실제 K-CBCL 규준표가 아닌 **시뮬레이션 규준**으로 변환한 값이다. 판정 기준·척도 간 관계는 일관되지만 원점수와 T점수의 대응은 실제 규준과 다르다.
- 이름·생년월일 등은 무작위로 조합한 가상 정보지만 식별 정보로 취급한다(G-09).
