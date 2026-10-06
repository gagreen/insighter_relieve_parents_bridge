# content/ — 콘텐츠·정책 데이터 형식

PoC 코드가 읽는 '미리 만든 문장'과 '규칙 데이터'의 형식 정의다. 내용은 구현 1~2일차에 채운다.
작성 규칙은 `specs/poc.md` 7장, 관련 규칙은 `CLAUDE.md` G-01·G-03·G-04·G-06.

- 인코딩 UTF-8, JSON.
- 모든 항목에 고유 `id`. 응답의 `evidence_ids`와 근거 칩이 이 id를 가리킨다.
- 숫자는 문장에 직접 쓰지 않고 자리표시자로 둔다. 코드가 payload에서 채운다.
- 숫자 자리표시자 바로 뒤에 조사를 두지 않는다. 단위를 붙인다(`{t}점으로`, `{rank_from_top}%에`). `tests/test_content.py`가 검사한다.
- 아래 예시 값은 형식 설명용이며 실제 콘텐츠가 아니다.

## 파일 목록

| 파일 | 용도 | 사용처 |
| --- | --- | --- |
| `scale_cards.json` | 척도 설명 카드 (척도 × 범위 1장) | PoC1-04, 응답 근거 |
| `summary_templates.json` | 한 줄 요약 템플릿 | PoC1-03 |
| `phrases.json` | 백분위 문장, 고정 문구, 범위 밖·입력 오류·API 오류 안내 | PoC1-02, 07 / PoC2-01, 06, 10 |
| `glossary.json` | 용어사전 (표기·검사 용어·해석 표현) | 보고서 원문 낱말 풀이(PoC1-10), 응답 근거 |
| `safe_responses.json` | 안전 응답 템플릿 | PoC2-05, 08 |
| `scale_terms.json` | 질문 속 표현 → 척도 연결 (안전 응답의 척도 찾기) | PoC2-05 |
| `crisis.json` | 위기 키워드, 위기 안내, 공공 상담 채널 | PoC2-03 |
| `intent_keywords.json` | 의도 분류 1차 키워드 | PoC2-04 |
| `guard_terms.json` | 진단명 사전, 금칙 표현 | PoC1-08, PoC2-08 |
| `name_word_exceptions.json` | 이름과 겹치는 일반 낱말의 용법 패턴 (마스킹 예외) | PoC2-02 |

## 자리표시자

| 이름 | 값 | 출처 |
| --- | --- | --- |
| `{scale_name}` | 척도 이름 | payload `scores[].name` |
| `{t}` | T점수 | payload `scores[].t` |
| `{percentile}` / `{rank_from_top}` | 백분위 / 100 − 백분위(반올림) | payload `scores[].percentile` |
| `{range_label}` | 범위 이름 | 판정 결과 + 정의 `range_labels` |
| `{clinical_list}` / `{borderline_list}` | 판정 결과가 clinical / borderline인 척도 이름 나열 ("A, B", payload 순서) | 판정 결과 + payload `scores[].name` |
| `{max_chars}` | 입력 길이 상한 ("1,000") | `config.MAX_INPUT_CHARS` (P-01) |

정의에 없는 자리표시자를 쓰면 콘텐츠 로드 시 오류로 처리한다(`bridge.content`). 파일별 허용 범위:

- `scale_cards.json`: `{scale_name}`, `{range_label}`만. 카드에는 숫자 자리표시자를 쓰지 않는다(숫자는 결과 view model에서만 채움, G-03).
- `summary_templates.json`: `{clinical_list}`, `{borderline_list}`만. 조건상 비어 있는 목록은 쓸 수 없다(예: `has_clinical: false` 템플릿의 `{clinical_list}`).
- `glossary.json`: 자리표시자 없음.

## 사전 검사 (PoC1-08)

`bridge.content.SENTENCE_FIELDS`에 적힌 문장 필드 전체를 `guard_terms.json`으로 검사하고, 자리표시자를 뺀 문장에 숫자가 없는지 확인한다(`tests/test_content.py`). 패턴 파일(`guard_terms.json`, `intent_keywords.json`, `crisis.json`의 `keywords`)과 연락처는 문장이 아니므로 제외한다. 새 콘텐츠 파일에 문장 필드가 있으면 `SENTENCE_FIELDS`에 추가한다.

## scale_cards.json

```json
[
  {
    "id": "card.KCBCL_4_17.attention.borderline",
    "assessment": "KCBCL_4_17",
    "scale": "attention",
    "range": "borderline",
    "title": "주의집중 문제",
    "what_it_asks": "(이 척도가 묻는 행동을 쉬운 말로)",
    "behavior_examples": ["(행동 예시)", "(행동 예시)"],
    "position_text": "{scale_name} 점수는 {range_label}에 있습니다.",
    "report_recommendation": "(보고서 권고 수준을 넘지 않는 문장)",
    "status": "draft",
    "version": 1,
    "reviewed_at": null
  }
]
```

- `status`: `draft | reviewed`. PoC에서는 모두 `draft`.
- (assessment, scale, range) 조합은 유일해야 한다. `range`는 `normal | borderline | clinical`. 정의에 없는 척도·미실시 항목은 카드 없이 보고서 원문을 보여준다(PoC1-04).
- 권고 수준: normal 카드에는 '권고'를 쓰지 않고, borderline 카드에는 '전문'·'정밀'을 쓰지 않는다(테스트로 확인).

## summary_templates.json

```json
[
  {"id": "sum.none",       "when": {"has_clinical": false, "has_borderline": false}, "text": "(모든 영역이 또래 평균 범위일 때)"},
  {"id": "sum.borderline", "when": {"has_clinical": false, "has_borderline": true},  "text": "(… {borderline_list} …)"},
  {"id": "sum.clinical",   "when": {"has_clinical": true,  "has_borderline": false}, "text": "(… {clinical_list} …)"},
  {"id": "sum.both",       "when": {"has_clinical": true,  "has_borderline": true},  "text": "(… {clinical_list} … {borderline_list} …)"}
]
```

- 네 조건이 빠짐없이, 겹치지 않게 있어야 한다.

## phrases.json

```json
{
  "fixed_notice_results": "선별 검사이며 진단이 아닙니다.",
  "percentile_known": "상위 약 {rank_from_top}%에 해당하는 점수입니다.",
  "percentile_known_lower": "하위 약 {percentile}%에 해당하는 점수입니다.",
  "direction_note_lower": "(점수가 낮을수록 어려움이 많이 보고되었다는 방향 안내)",
  "percentile_unknown": "(백분위 null = 하한 50T: 가장 낮은 점수, 평균과 비슷하거나 낮음, 백분위 따로 계산 안 함)",
  "not_administered": "(미실시 표시 문장)",
  "fixed_notice_qa": "(질문 도우미 고정 안내)",
  "interpretive_note": "(해석 표현 풀이 뒤에 붙는 상담 안내)",
  "report_phrase_note": "(보고서의 '{term}' 표현 … 상담 질문 노트 문장)",
  "report_phrase_saved": "(상담 질문 저장 확인)",
  "out_of_scope": "(고객센터·예약 안내)",
  "input_empty": "(빈 입력 안내)",
  "input_too_long": "(… {max_chars}자 … 나눠 질문 안내)",
  "no_evidence": "(보고서에 해당 내용이 없다는 안내)",
  "api_error": "(일시 오류 안내)",
  "note_saved": "(질문이 상담 노트에 저장되어 상담사가 상담 전에 확인한다는 안내)",
  "safe_scale_fact": "보고서에서 {scale_name} 점수는 T점수 {t}점으로, {range_label}에 있습니다.",
  "safe_report_quote": "(보고서 인용 도입) “{quote}”",
  "screening_note": "(선별 검사이며 진단이 아니라는 안내)",
  "glossary_answer": "‘{term}’의 뜻: {plain}",
  "glossary_answer_unnamed": "질문하신 표현의 뜻: {plain}",
  "diagnosis_term_scale": "(관련 척도 안내) ‘{scale_name}’",
  "prep_intro": "(상담 준비 안내 도입)",
  "prep_memo": "(관찰 장면 메모 안내)",
  "prep_notes_intro": "(저장된 질문 목록 머리말)",
  "prep_no_notes": "(저장된 질문이 없을 때 안내)",
  "prep_closing": "(상담사가 미리 확인한다는 안내)"
}
```

- 백분위 문장은 척도의 `direction`(정의의 group 또는 척도 항목, `specs/poc.md` 2-2)으로 고른다: `higher_is_worse` → `percentile_known`, `lower_is_worse` → `percentile_known_lower` + `direction_note_lower`, direction 없음 → 문장 없이 숫자만.
- 키별 허용 자리표시자는 `bridge.content.PHRASE_PLACEHOLDERS`. M1 키(`M1_PHRASE_KEYS`: 백분위·미실시·고정 문구 6개 + 낱말 풀이·상담 질문 저장 3개)는 결과 화면의 필수 키다. 2일차 키는 PoC-2 구현 때 추가하고 `QA_PHRASE_KEYS`에 적는다.
- `input_too_long`은 `{max_chars}`만 쓴다(문장에 숫자를 직접 쓰지 않는다).
- `note_saved`는 노트에 저장하는 모든 응답(안전 응답, 근거 없음, 부분 답변, API 오류) 끝에 코드가 붙인다(`specs/poc.md` 1-1 R-2). 그래서 `no_evidence`·`api_error`에는 저장 안내를 쓰지 않는다.
- `safe_report_quote`의 `{quote}`는 보고서 관찰 소견 첫 줄 원문이다. 인용 끝말에 따라 조사가 달라지므로 인용 뒤에 조사를 붙이지 않는다.
- `glossary_answer`(낱말 뜻 질문, `specs/poc.md` PoC2-14)의 `{term}`·`{plain}`은 용어사전의 표현과 풀이다. 표현이 금칙 표현에 걸리면 `glossary_answer_unnamed`로 풀이만 쓴다.
- `prep_*`는 상담 준비 안내(PoC2-15) 조립용이다. 상담 절차·시간·담당자 자격처럼 근거가 없는 서비스 정보는 쓰지 않는다.

## glossary.json

```json
[
  {"id": "term.t_score", "kind": "term", "term": "T점수", "aliases": ["T 점수", "티점수"], "plain": "(쉬운 설명)", "status": "draft"},
  {"id": "term.notation_t", "kind": "notation", "term": "T=", "aliases": [], "patterns": ["T\\s*=\\s*\\d+"], "plain": "(읽는 법)", "status": "draft"},
  {"id": "term.worsening", "kind": "interpretive", "term": "악화 가능성", "aliases": [], "plain": "(낱말 뜻만)", "status": "draft"}
]
```

- 풀이(`plain`)는 객관적인 뜻만 쓴다. 긍정·부정 평가, 완화 문구("~라는 뜻은 아닙니다"), 이 아이에게 해당한다는 단정을 쓰지 않는다(G-01, `tests/test_glossary_match.py`가 일부 표현을 검사).
- `kind`(PoC1-10): `notation` 표기(숫자 읽는 법만) / `term` 검사 용어 / `interpretive` 해석 표현. 해석 표현은 아이에 대한 판단 없이 낱말 뜻만 쓰고, 화면에서 `phrases.interpretive_note`와 [상담 질문으로 저장]이 붙는다(G-01).
- 찾기: `term`·`aliases`는 글자 그대로, `patterns`(선택)는 정규식. 보고서 원문에서 가져온 찾기 표현이라 사전 검사 대상이 아니고 `plain`만 검사한다. 원문 표현에 금칙어가 있으면(`악화`) 풀이에서는 다른 말로 설명한다.
- 겹치면 긴 표현이 먼저 걸린다. 증후군 척도 이름 안에 걸리는 짧은 표현은 넣지 않는다(예: '미성숙' 대신 '미성숙한 행동', `tests/test_glossary_match.py`).
- `term`·`aliases`는 파일 전체에서 유일해야 한다. `status`는 `draft | reviewed`(PoC는 모두 draft).

## safe_responses.json

```json
[
  {
    "id": "safe.diagnosis",
    "kind": "diagnosis",
    "empathy": "(보호자의 마음을 받는 문장. 없으면 null)",
    "body": "(무엇을 상담에서 다루는지)",
    "screening_note": true,
    "closing": "(준비 행동 안내)"
  }
]
```

- 종류(`kind`): `diagnosis`, `parenting`, `low_confidence`, `guard_fallback`, `diagnosis_term`(진단명 뜻, 2026-10-06). 종류마다 정확히 1개.
- 문장 필드(`empathy`, `body`, `closing`)에는 자리표시자를 쓰지 않는다. 척도 사실·보고서 인용·선별 검사 안내·노트 저장 안내는 `phrases.json` 문구로 코드가 조립한다.
- 조립 순서(`specs/poc.md` PoC2-05): `empathy` → 질문에서 찾은 척도마다 `safe_scale_fact`(최대 `config.SAFE_MAX_SCALES`개) → 첫 척도의 관찰 소견 첫 줄 `safe_report_quote`(금칙 표현에 걸리면 생략) → `body` → `screening_note`(true일 때) → `note_saved` → `closing`.
- `empathy`는 보호자의 마음만 받는다. 아이 상태 판단, 안심·완화 문구("괜찮다", "~라는 뜻은 아니다")는 쓰지 않는다(G-01, 2026-10-05).
- `diagnosis_term`은 조립 순서가 다르다: `body` → `diagnosis_term_scale` + 관련 척도 카드의 `what_it_asks` → `safe_scale_fact` → `screening_note` → `note_saved` → `closing`. 진단명은 응답에 다시 쓰지 않는다(G-01).

## scale_terms.json

```json
[
  {"id": "terms.KCBCL_4_17.attention", "assessment": "KCBCL_4_17", "scale": "attention",
   "terms": ["(질문에 나올 수 있는 표현)"], "status": "draft"}
]
```

- 척도 이름(payload `scores[].name`)은 자동으로 찾으므로 여기에는 그 밖의 표현만 둔다. 이름 일치가 표현 일치보다 우선한다.
- (assessment, scale) 조합과 같은 검사 안의 표현은 유일해야 한다. `scale`은 판정 기준 정의의 `scales` 키.
- 진단명 → 척도 연결은 '어느 보고서 사실을 보여 줄지'를 고르는 데만 쓰고 화면에 연결 관계를 출력하지 않는다(G-01). 상담사 검수 전 초안(`status: draft`).
- 패턴 데이터라 사전 검사(PoC1-08) 대상이 아니다.

## crisis.json

```json
{
  "keywords": [
    {"id": "crisis.kw.001", "pattern": "(표현)", "type": "literal", "category": "child_safety"}
  ],
  "message": "(위기 안내 문장)",
  "channels": [
    {"name": "(기관·채널명)", "contact": "(연락처)", "source_url": "(공식 출처)", "checked_at": "YYYY-MM-DD"}
  ]
}
```

- `type`: `literal | regex`. `category`: `child_safety | caregiver_distress`.
- 원문과 공백을 지운 문장 양쪽에서 찾는다. 관용어("힘들어 죽겠어요")와 공격성 행동("친구를 때려요")은 잡지 않는다(`specs/poc.md` PoC2-03).
- `channels`는 공식 출처 확인 전에는 비워 둔다. 위기 안내는 `message` 뒤에 `- 이름: 연락처` 줄로 채널을 붙인다.

## intent_keywords.json

```json
{
  "diagnosis":    [{"id": "intent.dx.001", "pattern": "(표현)", "type": "literal"}],
  "parenting":    [],
  "consult_prep": [],
  "out_of_scope": [],
  "explain":      [],
  "meaning":      []
}
```

- 키는 정확히 위 6개. `meaning`은 의도가 아니라 뜻을 묻는 표현이다(진단 우선 예외 판정, `specs/poc.md` PoC2-04, 2026-10-06). `id`는 파일 전체에서 유일하다. `type`: `literal | regex`.
- diagnosis에 걸리면 다른 의도와 겹쳐도 diagnosis다. 단, `meaning`이 걸리고 진단 키워드가 모두 용어사전 표현 안에 있으면 낱말 뜻(`glossary`), 진단명의 뜻만 묻으면 진단명 뜻 안전 응답이다(`bridge.rules.intents.diagnosis_subroute`). 그 밖에 두 개 이상의 의도에 걸리거나 아무 것에도 걸리지 않으면 LLM 2차 분류로 넘긴다(PoC2-04, 2026-10-04 결정).
- `guard_terms.json`의 `diagnosis_name` 항목은 모두 diagnosis 키워드로도 잡혀야 한다(테스트로 확인). 진단명을 사전에 추가하면 여기에도 추가한다.
- 모든 검사가 공유하는 파일이므로 특정 검사의 척도 이름을 넣지 않는다(G-12).
- 위기 키워드는 여기가 아니라 `crisis.json`에 둔다(위기 검사가 먼저 실행됨).

## name_word_exceptions.json

```json
[
  {"id": "nw.insa", "word": "인사", "keep_patterns": ["인사(를|도|는|만)?\\s*(하|해|했)", "인사말"], "status": "draft"}
]
```

- 아동의 성을 뺀 이름이 `word`와 같을 때만 쓴다. `keep_patterns`(정규식)에 걸린 범위 안의 이름은 가리지 않고, 나머지는 가린다. 전체 이름은 항상 가린다(`specs/poc.md` PoC2-02).
- `id`·`word`는 유일하고, 패턴은 컴파일되어야 한다. 패턴 데이터라 사전 검사(PoC1-08) 대상이 아니다.

## guard_terms.json

```json
[
  {"id": "guard.dx.001", "pattern": "(진단명)",    "type": "literal", "category": "diagnosis_name"},
  {"id": "guard.fb.001", "pattern": "(금칙 표현)", "type": "regex",   "category": "prognosis"}
]
```

- `category`: `diagnosis_name | diagnosis_possibility | treatment | medication | institution | prognosis | reassurance | threat`.
- 콘텐츠 전체와 모든 AI 응답에 같은 목록을 적용한다.
- 원칙: 진단명·치료법·약 이름·기관 이름과 권고·판단 형태("치료가 필요", "가능성이 높", "좋아질", "괜찮", "심각")를 막는다. '진단'·'치료'라는 단어 자체는 경계 안내("진단이 아닙니다", "진단·치료에 관한 판단은 상담에서 다룹니다")에 필요하므로 막지 않는다. '장애'는 단어 전체를 막는다.
- literal은 대소문자를 무시하고, 원문과 공백을 지운 문장 양쪽에서 찾는다.
