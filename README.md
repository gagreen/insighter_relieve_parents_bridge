# 아맘때 '상담 브리지' PoC

검사 결과 보고서 수령 ~ 상담 전 공백을 메우는 PoC. 설계 원칙: **판정은 규칙이, 문장은 AI가, 검수는 사람이.**
요구사항은 [specs/poc.md](specs/poc.md), 작업 규칙은 [CLAUDE.md](CLAUDE.md).

> 작성 중. 각 항목은 구현이 끝나는 대로 채운다.

## 실행 방법

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # ANTHROPIC_API_KEY 입력
python -m bridge.db init           # SQLite 스키마 생성 + 샘플 적재
pytest
streamlit run app/main.py          # 데모 화면 (결과 · 질문 도우미 · 상담 브리프)
python -m bridge.brief R-KCBCL_4_17-035   # 브리프 텍스트 (질문 정리 LLM 1회, --no-llm이면 생략)
```

## 사용 모델·API

- Anthropic Messages API (Python SDK)
- 기본 `claude-haiku-4-5-20251001`, 비교용 `claude-sonnet-5-5`

## 환경 변수

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | 예 | Anthropic API 키 |
| `LLM_MODEL` | 아니오 | 기본 `claude-haiku-4-5-20251001` |
| `ANTHROPIC_CUSTOM_HEADERS` | 아니오 | 워크스페이스에 묶이지 않은 API 키를 쓸 때 `anthropic-workspace-id: <워크스페이스 ID>` |

`.env`는 실행 시 자동으로 읽는다. 셸에 이미 설정된 환경 변수가 있으면 그 값이 우선한다.

## 예상 비용

(평가 실행 후 기재)

## AI 도구 사용 내역

| 도구 | 용도 |
| --- | --- |
| Claude Code | 명세·테스트·코드 작성. 척도 설명 카드·한 줄 요약 템플릿·용어사전·금칙 사전 초안 작성(모두 `draft`, 상담사 검수 전) |

## 한계

- 척도 설명 카드는 상담사 검수 전 초안이다.
- 샘플 데이터의 T점수는 실제 K-CBCL 규준이 아닌 시뮬레이션 규준으로 만든 가상 값이다.
- 마스킹은 아동 이름(3글자 이상, 복성 미지원), 전화번호, 이메일, 붙여 쓴 초·중·고등학교 이름만 대상으로 한다. 생년월일, 유치원·어린이집 이름, 아동 외 가족 이름, 학교 줄임말은 마스킹하지 않는다.
