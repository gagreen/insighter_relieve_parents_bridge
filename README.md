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
```

## 사용 모델·API

- Anthropic Messages API (Python SDK)
- 기본 `claude-haiku-4-5-20251001`, 비교용 `claude-sonnet-5-5`

## 환경 변수

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | 예 | Anthropic API 키 |
| `LLM_MODEL` | 아니오 | 기본 `claude-haiku-4-5-20251001` |

## 예상 비용

(평가 실행 후 기재)

## AI 도구 사용 내역

(작성 예정)

## 한계

- 척도 설명 카드는 상담사 검수 전 초안이다.
- 샘플 데이터의 T점수는 실제 K-CBCL 규준이 아닌 시뮬레이션 규준으로 만든 가상 값이다.
