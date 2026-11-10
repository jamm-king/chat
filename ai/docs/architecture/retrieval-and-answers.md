# 검색·답변 실행

`POST /internal/v1/retrieval/search`와 `POST /internal/v1/answers`를 구현했다. 요청·응답 필드는 [연동 명세](../api/references.md)를 따른다. 기존 자료 ID·DB 테이블을 유지하며 새 마이그레이션은 필요하지 않다.

## 활성화

pgvector와 OpenAI 키를 준비하고 `.env`에 다음을 설정한다. 기존 `.env`를 예제 파일로 덮어쓰지 않는다.

```dotenv
INDEXING_ENABLED=true
RAG_ENABLED=true
ANSWER_MODEL=gpt-6-luna
```

GPT-6.0 Luna는 공식 API ID `gpt-6-luna`를 사용한다. 생성은 LangChain `ChatOpenAI`의 Responses API와 strict JSON schema 출력을 사용한다. `store=False`, AUTO의 읽기 전용 검색 도구만 허용, 웹 검색·자동 재시도 없음이며 공급자 오류를 다른 모델 호출로 우회하지 않는다. 모델은 ANSWER_MODEL로 명시적으로 바꿀 수 있다. [OpenAI 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-luna), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai).

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| RAG_ENABLED | false | 검색·생성 공급자 활성화. 키 필수 |
| ANSWER_MODEL | gpt-6-luna | 기본 생성 모델 |
| ANSWER_PROVIDER_TIMEOUT_SECONDS | 40 | 단일 생성 호출 기한, 최대 55초 |
| ANSWER_MAX_OUTPUT_TOKENS | 4096 | 생성 출력 토큰 상한. 최종 본문은 최대 16000자 |
| ANSWER_CONTEXT_BUDGET_BYTES | 64000 | UTF-8 기준 보수적인 문맥 예산 |

자료 검색은 저장된 EMBEDDING_MODEL·EMBEDDING_DIMENSIONS와 현재 설정이 일치해야 한다. 서로 다른 모델 공간·차원을 섞지 않는다. 불일치하면 409 RESOURCE_NOT_READY이며 기존 자료를 자동 재색인하지 않는다. RAG만 실행하려면 INDEXING_ENABLED=false로 둘 수 있지만 검색할 자료는 이미 READY여야 한다. 비활성 상태의 실제 검색·생성은 409 OPERATION_NOT_AVAILABLE이다. 빈 자료 목록의 검색과 명시적 RESOURCE 근거 부족은 외부 호출 없이 제공하지만 AUTO는 판단용 모델이 필요하므로 비활성 시 빈 목록도 409다.

## 처리 경계

- SearchResources: 전체 범위 검증 → 질문 임베딩 → 코사인 거리 검색 → 범위 재검증.
- GenerateAnswer: 기존 GENERAL·RESOURCE 흐름 유지. AUTO는 범위·예산 확인 → 도구를 제공한 LLM 호출 → 직접 답변 또는 검색 1회 → 필요 시 최종 생성 → 출처·범위 검증.
- RetrievalStore: 사용자·자료·색인 모델·차원을 SQL로 제한하고 PostgreSQL pgvector에서 정렬한다. 동점은 자료 ID·청크 순서·청크 ID로 정한다. SQLite의 Python 거리 계산은 자동 테스트용이다.
- AnswerGenerator: 기존 명시적 모드의 모델 호출과 구조화 응답 변환을 담당한다.
- AutoAnswerGenerator: LangChainAnswerGenerator가 함께 구현한다. 모델에 query·top_k만 받는 search_resources 도구를 제공하고, 호출 시 application이 고정된 사용자·자료 범위에서 SearchResources를 실행한다. 도구와 추론 상태는 요청별 로컬 상태로 관리하며 공유 객체에 보관하지 않는다.

최종 응답에서 모델이 반환하는 것은 상태·본문·청크 ID·발췌뿐이다. 제목·URL·자료 ID는 서버가 실제 검색 결과에서 채운다.

검색은 관련도 순 topK이며 유사도 임계값이나 재순위 모델은 없다. 검색 결과가 질문의 답을 포함한다는 보장은 없으므로 생성기는 근거가 부족하면 INSUFFICIENT_EVIDENCE를 반환하도록 지시한다. 검색 청크는 신뢰하지 않는 데이터로 전달하고 문서 안의 지시를 따르지 않도록 시스템 지침을 둔다. 의미상 답변 품질·프롬프트 공격 내성은 실제 고정 자료 평가가 필요하다.

## 문맥·출처·삭제

문맥 예산 중 4096바이트는 지침·출력 스키마 등을 위해 예약한다. AUTO는 Responses의 추론·도구 호출 연속 처리를 위한 메시지 크기도 추가 차감하고, 최종 호출용 이력을 다시 제한한다. 추론 항목은 reasoning.encrypted_content로 받아 store=False 상태에서 도구 결과와 함께 전달한다. 현재 질문은 자르지 않는다. 근거를 먼저 넣고 남은 예산에서 오래된 USER/ASSISTANT 쌍부터 제외한다. 이것은 정확한 공급자 토큰 계산이 아닌 보수적인 앱 입력 제한이다. 현재 질문만으로 초과하면 400 CONTEXT_LIMIT_EXCEEDED, RESOURCE에서 넣을 수 있는 근거가 없으면 생성 없이 근거 부족이다. 검색용 질문이 공급자 임베딩 입력 제한을 초과하는 등 공급자가 요청을 거절하면 오류로 반환하며 질문을 조용히 자르지 않는다.

RESOURCE의 출처는 검색된 청크에 한정한다. excerpt는 원문 청크의 1~1000자 연속 텍스트인지 확인하고 중복 청크·알 수 없는 청크·잘못된 참조 번호·본문에 없는 출처를 거절한다. 구조가 잘못되면 502 AI_PROVIDER_ERROR이며 재생성하지 않는다. 본문이 16000자를 넘으면 문장·줄 경계를 우선해 줄이고 사용하지 않는 출처를 제거·재번호화한다. 줄인 본문에 출처가 하나도 남지 않으면 근거 부족이다.

삭제·색인 공개와 같은 잠금을 사용해 초기 범위와 최종 색인 버전을 비교한다. 생성 대기 중 잠금을 잡지 않는다. 삭제 실패로 행이 남아도 현재 프로세스의 삭제 제외 표시를 적용한다. 응답 JSON 생성 직전 범위를 다시 검사하고 변경되면 409 RESOURCE_SCOPE_CHANGED다. Backend도 최종 저장·반환 전에 자료 범위를 확인한다.

검색 HTTP 기한은 15초, 답변은 전체 60초다. 시간 초과 또는 서버 요청 핸들러 태스크 취소를 감지하면 늦게 끝난 처리는 다음 단계 호출을 시작하지 않는다. 브라우저 연결 종료만으로 핸들러 취소가 자동 보장되는 것은 아니다. 이미 전송한 공급자 호출의 전송·과금 취소는 보장하지 않는다. 자동 재시도·대화 저장·스트리밍·영속 작업 큐는 추가하지 않는다. 요청 추적·오류 envelope·서비스 인증은 기존 내부 API 규칙을 따른다.

## 확인 방법

1. COLLECT_AND_INDEX 작업이 READY로 끝난 자료 ID를 준비한다.
2. `/docs`에서 서비스 토큰으로 인증하고 `/internal/v1/retrieval/search`에 userId·query·resourceIds·topK를 보낸다.
3. `/internal/v1/answers`에 RESOURCE·message·동일 자료 목록을 보내고 발췌가 실제 본문에 있는지 확인한다.
4. GENERAL 요청은 resourceIds 없이 보내고 citations=[]인지 확인한다.
5. 다른 사용자 자료·COLLECTED·삭제 자료를 섞으면 전체 요청이 실패하는지 확인한다.

`tests/test_rag.py`는 모의 공급자와 저장소를 통한 HTTP·출처·범위·기한을 검증한다. `tests/test_answer_provider.py`는 실제 LangChain/OpenAI SDK와 모의 HTTP 전송으로 Responses 요청·구조화 응답·거절·오류를 검증한다. 실제 OpenAI 모델 호출·계정별 모델 접근 권한·답변 품질을 검증한 것으로 해석하지 않는다. 별도 AI_TEST_POSTGRES_URL 설정 시 실제 pgvector 검색과 모델·차원·사용자 필터도 검사한다.

AUTO는 범용 반복 에이전트 대신 LangChain 도구와 구조화 출력을 결합한 제한된 워크플로다. tests/test_auto_provider.py는 실제 SDK의 도구 스키마·추론/도구 결과 전달·단일 호출·오류·요청 격리를 검증하고, tests/test_auto_answers.py는 HTTP·DB 연계·응답 모드·범위·삭제·기한을 확인한다. 실제 OpenAI 호출은 하지 않는다.
