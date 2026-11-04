# Backend → AI API 계약

2026-11-04 · API 명세 v2.0.0 · **COLLECT·COLLECT_AND_INDEX·자료 삭제·RAG 검색·답변 구현**

기준 결정은 [Backend–AI 연동 구조](../architecture/backend-ai-contract.md)다. 현재 OAuth는 [현행 OAuth 계약](notion-oauth.md), 현재 동기 페이지 조회·저장은 실행 중 `/openapi.json`을 따른다. 이 문서와 [정적 OpenAPI](openapi.json)는 현재 수집·색인·자료 삭제·RAG 계약을 함께 기술한다. 실제 구현 목록은 런타임 스키마로 확인한다. 2026-10-29의 공개 URL 스크래핑 계약은 이 문서로 대체한다.

v2.0.0은 정적 계약 문서의 버전이다. 목표 경로는 `/internal/v1`을 유지하며, 배포된 API의 호환성을 확인했다는 의미는 아니다.

## 공통 규칙

- 로컬 AI 주소: `http://localhost:8001`.
- Backend가 사용자 인증 후 `Authorization: Bearer <AI_SERVICE_TOKEN>`으로 호출한다. OAuth 콜백은 이 서비스 토큰 대상이 아니다.
- userId는 Backend 로그인 사용자이며 AI도 연결·자료·색인을 사용자 범위로 제한한다.
- ID는 UUID, 시간은 UTC RFC 3339, JSON은 UTF-8. 내부 API 필드명은 camelCase다. 현행 OAuth·페이지 API 응답의 snake_case는 별도 계약이다.
- POST 본문은 최대 256 KiB이며 알 수 없는 필드를 거절한다. GET·DELETE에는 본문이 없다.
- 선택 UUID 헤더 X-Request-Id는 요청 추적용이며 멱등성을 보장하지 않는다. 미지정 시 생성하고 잘못된 형식은 400이다. 응답에는 실제 ID와 `Cache-Control: no-store`를 포함한다.
- resourceId와 jobId는 Backend가 발급한다. 별도 ai_resource_id는 도입하지 않는다.

| Method | 경로 | 정상 응답 |
| --- | --- | --- |
| POST | `/internal/v1/ingestions` | 신규 202, 동일 작업 200 |
| GET | `/internal/v1/ingestions/{jobId}?userId={userId}` | 200 |
| DELETE | `/internal/v1/resources/{resourceId}?userId={userId}` | 204 |
| POST | `/internal/v1/retrieval/search` | 200 |
| POST | `/internal/v1/answers` | 200 |

## 1. 선택한 Notion 페이지의 수집·색인 접수

`POST /internal/v1/ingestions`

```json
{
  "jobId": "22222222-2222-4222-8222-222222222222",
  "userId": "11111111-1111-4111-8111-111111111111",
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "connectionId": "44444444-4444-4444-8444-444444444444",
  "pageId": "55555555-5555-4555-8555-555555555555",
  "parentResourceId": null,
  "operation": "COLLECT"
}
```

parentResourceId만 선택 사항이며 미지정·null은 최상위 자료다. 다른 필드는 필수다. URL을 받지 않고 사용자가 선택한 연결·페이지를 받는다. AI는 OAuth 토큰으로 Notion 공식 API를 호출한다. URL 스크래핑·브라우저 렌더링·자동 재귀 수집은 하지 않는다.

### 접수와 실행

AI는 최소 입력·연결 소유권·작업 및 자료 ID 충돌을 검사한 뒤 메모리 작업을 등록하고 `202`와 QUEUED 작업을 반환한다. `Location`은 작업 조회 경로이며 `Retry-After: 2`를 제공한다. Notion 본문 조회나 임베딩은 접수 응답 후 실행한다. 해당 페이지의 현재 접근 권한은 실행 시 확인한다.

- COLLECT: 원본·본문·참조 저장. 정상 완료는 작업 SUCCEEDED, 자료 COLLECTED, result.ready=false.
- COLLECT_AND_INDEX: 수집·청킹·임베딩·색인 공개. 정상 완료는 작업 SUCCEEDED, 자료 READY, result.ready=true.
- 색인 설정 비활성 시 COLLECT_AND_INDEX는 `409 OPERATION_NOT_AVAILABLE`로 접수 거절한다. 요청을 COLLECT로 낮춰 처리하지 않는다.
- 같은 jobId·같은 입력은 메모리에 있는 현재 작업을 200으로 반환하며 재실행하지 않는다. 다른 입력으로 같은 jobId를 쓰면 `409 JOB_ID_CONFLICT`다. UUID는 정규화하고 누락 parentResourceId는 null로 비교한다.
- 같은 자료의 동시 작업은 `409 INGESTION_IN_PROGRESS`다. 기존 resourceId의 userId·connectionId·pageId·부모를 바꿀 수 없다. 다른 원본을 등록하려면 새 resourceId를 사용한다.
- 이미 수집된 자료의 중복 COLLECT는 `409 RESOURCE_ALREADY_COLLECTED`, 준비된 자료는 `409 RESOURCE_ALREADY_INDEXED`다.
- 기존 COLLECTED 자료는 새 jobId의 COLLECT_AND_INDEX로 승격할 수 있다. 저장한 스냅샷을 재사용하며 원문을 자동 재수집하지 않는다.
- 자식 등록은 같은 사용자의 같은 연결·실제 페이지 참조를 검증한다. 없는 연결·자료 또는 소유권 불일치는 404, 부모 참조 불일치는 `409 INVALID_PARENT_REFERENCE`다. DB 참조는 등록 대상이 아니다. 실패는 부모 상태를 변경하지 않는다.

### 작업 조회와 상태

`GET /internal/v1/ingestions/{jobId}?userId={userId}`

| 작업 상태 | 의미 | resourceStatus |
| --- | --- | --- |
| QUEUED | 접수·대기 | PROCESSING |
| EXTRACTING | Notion 본문 수집 | PROCESSING |
| EXTRACTED | 현재 페이지 본문 저장 완료, 다음 단계 진행 전 | PROCESSING |
| INDEXING | 청킹·임베딩·색인 작성 | PROCESSING |
| SUCCEEDED + COLLECT | 수집 작업 종료 | COLLECTED |
| SUCCEEDED + COLLECT_AND_INDEX | 검색 가능한 색인 공개 | READY |
| FAILED | 실패 종료 | FAILED |
| CANCELLED | 자료 삭제로 취소 | DELETED |

Frontend/Backend는 SUCCEEDED·FAILED·CANCELLED에서 작업 폴링을 멈춘다. EXTRACTED는 종료 상태가 아니며 COLLECT 완료를 기다리며 READY를 폴링하지 않는다. COLLECTED와 READY만 자료 처리 성공의 종료 상태다. 부분 색인은 공개하지 않는다.

```json
{
  "jobId": "22222222-2222-4222-8222-222222222222",
  "userId": "11111111-1111-4111-8111-111111111111",
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "operation": "COLLECT",
  "status": "SUCCEEDED",
  "resourceStatus": "COLLECTED",
  "createdAt": "2026-11-03T01:00:00Z",
  "startedAt": "2026-11-03T01:00:01Z",
  "completedAt": "2026-11-03T01:00:03Z",
  "result": {
    "title": "프로젝트 회의록",
    "canonicalUrl": "https://www.notion.so/55555555555545558555555555555555",
    "contentStatus": "complete",
    "referenceCount": 2,
    "ready": false,
    "chunkCount": 0,
    "indexedAt": null
  },
  "error": null
}
```

result는 성공 시에만 존재한다. COLLECT는 chunkCount=0, indexedAt=null이며 COLLECT_AND_INDEX 성공은 chunkCount>=1, indexedAt이 존재해야 한다. 실제 본문 잘림·unknown 블록이 있으면 contentStatus=partial로 보존한다. 부분 본문은 COLLECT 결과로 확인할 수 있지만, 색인 단계에서는 `CONTENT_INCOMPLETE`로 실패시켜 완전한 색인으로 오인하지 않는다. 참조 미수집은 partial 사유가 아니다. 빈 본문은 COLLECT로 저장할 수 있으나 색인할 텍스트가 없으면 `EMPTY_CONTENT`로 실패한다.

error는 실패·취소 시 code, message, retryable을 제공한다. 작업 실행 오류는 HTTP 200의 FAILED 작업으로 조회한다. 입력·서비스 인증·접수 오류는 HTTP 오류다. AI 작업 오류는 Backend 작업 레코드에 저장하고 자료 상세의 오류는 최신 작업에서 제공한다.

### 최소 실행 정책

초기 구현은 단일 AI 프로세스의 비동기 실행·메모리 작업 상태를 허용한다. 진행 작업은 현재 프로세스 실행 중 접수 후 10분 내 종료한다. 자동 재시도·백오프·별도 워커·영속 큐·재시작 복구는 제외한다. 진행 중에는 Retry-After: 2를 제공하며 Backend는 2~10초 간격으로 조회한다.

프로세스 재시작 후 없는 작업은 `404 JOB_NOT_FOUND`다. Backend는 작업 유실을 기록하고 폴링을 중단하며 자동 재접수하지 않는다. 연결·완료된 자료는 DB에 남는다. 사용자 재시도 전 자료의 남은 상태를 대조하고 중복 등록하지 않는다. 재시작 후 자동 복구·장기 작업 보존을 보장하지 않는다.

## 2. 자료 검색

`POST /internal/v1/retrieval/search`

```json
{
  "userId": "11111111-1111-4111-8111-111111111111",
  "query": "RAG에서 검색의 역할은 무엇인가요?",
  "resourceIds": ["33333333-3333-4333-8333-333333333333"],
  "topK": 5
}
```

`userId`, `query`, `resourceIds`는 필수다. 질문은 1~8,000자이며 공백만 있는 값은 금지한다. 자료 목록은 최대 100개이며 중복은 금지한다. `topK`는 기본 5, 범위 1~20이다.

응답은 `{"results": [...]}`다. 각 결과는 `resourceId`, `chunkId`, `title`, `content`, `rank`, `locator`를 갖는다. 관련도 순으로 최대 `topK`개를 반환하며 부족하면 더 적게 반환한다. 순위는 1부터 연속되고 원시 유사도 점수·페이지네이션은 제공하지 않는다. 결과가 없으면 `200`과 빈 배열이다.

**검색 범위:** Backend가 소유권과 READY 상태를 검증한 자료만 보낸다. `resourceIds` 생략은 `400`, `[]`는 빈 검색 범위다. AI도 사용자·자료·색인 공개 상태를 검색 필터로 적용한다. 지정 자료 중 하나라도 없거나 삭제되었으면 `404 RESOURCE_NOT_FOUND`, 모두 존재하지만 준비되지 않은 자료가 있으면 `409 RESOURCE_NOT_READY`다. 부분 결과를 조용히 반환하지 않는다.

## 3. 답변 생성

`POST /internal/v1/answers`

```json
{
  "userId": "11111111-1111-4111-8111-111111111111",
  "mode": "RESOURCE",
  "message": "RAG에서 검색의 역할을 설명해줘.",
  "history": [],
  "resourceIds": ["33333333-3333-4333-8333-333333333333"]
}
```

`userId`, `mode`, `message`는 필수다. `GENERAL`은 자료 검색 없이 답하며 `resourceIds`를 보내면 `400`이다. `RESOURCE`는 명시한 자료에서 검색하며 검색 API와 동일한 범위 검증을 적용한다. 현재 요청의 자료 범위만 사용하고 과거 이력의 자료 범위를 상속하지 않는다.

| 입력      | 규칙                                                                       |
| --------- | -------------------------------------------------------------------------- |
| message   | 현재 질문, 1~8,000자, 공백만 있는 값 금지                                  |
| history   | 기본 `[]`, 최대 20개. 각 항목은 `role`, `content`                    |
| role      | USER / ASSISTANT만 허용                                                    |
| content   | 항목당 1~8,000자, 공백만 있는 값 금지                                      |
| 이력 순서 | 오래된 순의 완료된 USER/ASSISTANT 쌍. 현재 질문·실패·생성 중 메시지 제외 |
| 전체 입력 | message와 history 텍스트 합계 최대 32,000자                                |

입력 예산이 부족하면 오래된 이력 쌍부터 제외하며 현재 질문은 자르지 않는다. 질문만으로 예산을 넘으면 `400 CONTEXT_LIMIT_EXCEEDED`다. MVP에서는 이력 요약·웹 검색·스트리밍을 제공하지 않는다. 답변은 기본 한국어이며 명시적인 언어 요청을 따른다.

### 응답 예제

```json
{
  "answerId": "55555555-5555-4555-8555-555555555555",
  "mode": "RESOURCE",
  "status": "ANSWERED",
  "content": "검색한 자료를 근거로 답변을 생성합니다.[1]",
  "citations": [
    {
      "citationId": "1",
      "resourceId": "33333333-3333-4333-8333-333333333333",
      "chunkId": "44444444-4444-4444-8444-444444444444",
      "title": "프로젝트 참고 자료",
      "excerpt": "RAG는 검색한 자료를 근거로 답변을 생성한다.",
      "locator": { "type": "URL", "url": "https://example.notion.site/reference-0123456789abcdef0123456789abcdef", "section": null }
    }
  ],
  "context": { "historyMessagesUsed": 0, "historyTruncated": false },
  "createdAt": "2026-10-28T06:01:00Z"
}
```

| status                | 의미                                     | 출처                                |
| --------------------- | ---------------------------------------- | ----------------------------------- |
| ANSWERED              | 답변 생성 완료                           | GENERAL은 없음, RESOURCE는 1개 이상 |
| INSUFFICIENT_EVIDENCE | RESOURCE에서 질문을 뒷받침할 근거가 부족 | 없음                                |
| REFUSED               | 모델·서비스 안전 정책에 따른 거절       | 없음                                |

모두 HTTP `200`이다. 근거 부족과 장애는 구분하며 시스템 장애를 정상 결과로 숨기지 않는다. RESOURCE의 빈 자료 목록은 검색·LLM 호출 없이 `INSUFFICIENT_EVIDENCE`를 반환하고 이력 사용 수는 0, 절단 여부는 false다. 자료 근거를 문맥에 넣을 수 없는 경우도 근거 부족으로 처리한다. 일반 지식으로 자동 전환하지 않으며 자료가 충돌하면 출처와 함께 충돌을 설명한다.

`content`는 최대 16,000자 Markdown이며 초과 시 문장 경계에서 축약하고 참조를 맞춘다. 출처는 최대 10개다. 본문의 `[1]`은 출처의 `citationId: "1"`과 대응하고 ID는 1부터 연속된다. 같은 청크는 같은 ID를 사용하며 본문 참조와 출처가 양방향으로 일치해야 한다. `excerpt`는 실제 청크에 존재하는 1~1,000자 연속 텍스트다. 구조 검증 실패는 `502 AI_PROVIDER_ERROR`로 반환하며 LLM 재호출로 자동 복구하지 않는다.

검색 결과·출처의 `locator`는 `type: URL`, 최종 원문 `url`, 절 제목 `section`으로 구성한다. 제목·절 제목은 최대 500자이며 없으면 `null`이다. URL은 최대 2,048자, 검색 청크 content는 최대 8,000자다. 정확한 문단 이동과 현재 웹페이지의 과거 내용 일치는 보장하지 않는다.

AI는 대화를 저장하지 않는다. Backend가 답변·출처 스냅샷을 함께 저장하고 안전한 Markdown으로 표시한다. `answerId`는 생성 결과 식별자이며 조회 API·멱등성 기능은 없다. Backend는 사용자별 활성 생성을 하나로 제한하고 대화 초기화 전의 늦은 답변을 버린다.

## 4. 자료 삭제

`DELETE /internal/v1/resources/{resourceId}?userId={userId}`

Backend는 먼저 DELETED로 표시하고 검색 요청 범위에서 제외한다. AI는 사용자 범위로 진행 작업을 취소·검색을 차단하고, 원본·본문·참조·청크·임베딩을 삭제한 뒤 204를 반환한다. 반복 삭제·없는 자료도 204이며 다른 사용자 데이터는 변경하지 않는다. 늦은 수집·색인 결과가 자료를 다시 공개하지 않도록 완료 반영과 조율한다.

부모 삭제는 해당 자료에만 적용하고 자식 자료는 독립적으로 유지하며 부모 연결을 해제한다. 자동 연쇄 삭제는 하지 않는다. 과거 답변과 출처 스냅샷은 Backend에 유지하며 이 API로 지우지 않는다.

AI 삭제가 실패하면 503, 기한 초과면 504다. Backend는 검색 제외를 유지하고 AI 데이터 삭제 미완료를 기록한다. 소프트 삭제만 수행한 상태를 AI 물리 삭제 완료로 표시하지 않는다. 검색·답변 응답 직전 자료 범위가 바뀌면 `409 RESOURCE_SCOPE_CHANGED`이며 Backend도 저장·반환 전 재검증한다.

### 현재 삭제 구현과 제약

삭제 API는 구현돼 있다. 현재 저장된 원본·본문·참조는 한 자료 행에 있으므로 해당 행을 삭제한다. 청크·벡터·색인 완료 레코드도 같은 삭제 트랜잭션으로 제거한다. RAG 검색·답변에서도 삭제 제외와 응답 직전 범위 재검증을 적용한다. Notion 원문을 수정·삭제하는 API는 호출하지 않는다.

- 진행 중인 해당 사용자·자료 작업은 CANCELLED, resourceStatus=DELETED, error.code=RESOURCE_DELETED, retryable=false가 된다. 이미 전송한 Notion HTTP 요청을 강제 중단하지는 않지만 늦게 돌아온 결과는 저장하지 않는다.
- 동일 자료의 수집 완료 반영과 삭제는 같은 잠금으로 조율한다. 삭제가 먼저면 저장하지 않고, 저장이 먼저면 저장 행을 삭제한다.
- SUCCEEDED/FAILED 등 이미 종료한 작업은 과거 스냅샷으로 유지한다. 과거 SUCCEEDED의 COLLECTED를 현재 자료 상태로 덮어쓰지 않도록 Backend의 DELETED를 우선한다.
- 삭제한 자료 ID의 새 수집 접수는 409 RESOURCE_DELETED다. 기존 CANCELLED 작업의 정확한 재요청은 200/CANCELLED다. 삭제 후 같은 원본을 사용자가 다시 등록하려면 새 resourceId·jobId를 사용한다.
- 자식 자료는 유지하고 parentResourceId를 null로 해제한다. 부모 삭제 전에 이미 접수한 자식도 독립 자료로 완료할 수 있다. 삭제한 부모에 새 자식 등록은 거절한다.
- 원본·본문·참조 행 삭제 실패는 503 RESOURCE_DELETE_FAILED, 처리 기한 초과는 504 RESOURCE_DELETE_TIMEOUT이다. 성공으로 숨기지 않고 재시도 가능 여부를 반환한다. 요청의 현재 프로세스 내 제외 표시는 유지하며 기존 자료 목록·조회에서도 제외한다.
- 삭제 이력은 메모리이며 재시작·다중 프로세스에 걸친 제외 보장은 없다. 성공한 물리 삭제는 DB에 남지 않지만, 삭제 실패 후 재시작하면 남은 행을 AI가 다시 읽을 수 있다. Backend는 DELETED 상태를 유지하고 자료를 요청 범위에서 제외한 뒤 명시적으로 삭제를 재시도한다. 영속 삭제 이력·자동 복구는 후속이다.

## 5. 오류·호환성과 구현 순서

목표 API 오류는 `{error: {code, message, retryable, details}, requestId}`다. 현재 OAuth는 detail 형식이므로 같은 형식이라고 가정하지 않는다. Notion 401은 NOTION_REAUTHORIZATION_REQUIRED, 403은 NOTION_ACCESS_DENIED, 404는 NOTION_PAGE_NOT_FOUND로 분류한다. 404는 삭제와 미공유를 구분할 수 없음을 안내한다. 공급자 오류 본문·토큰·코드·쿠키는 로그나 응답에 노출하지 않는다.

| 단계 | AI 기한 | Backend 읽기 타임아웃 |
| --- | --- | --- |
| 작업 접수·조회 | 5초 | 10초 |
| 삭제 | 10초 | 15초 |
| 검색 | 15초 | 20초 |
| 답변 | 60초 | 65초 |

retryable은 사용자가 다시 시도할 수 있다는 정보이며 자동 재시도 지시가 아니다. Retry-After는 폴링·사용자 재시도 대기 시간이다. requestId는 멱등성 키가 아니다.

현재 POST `/internal/v1/ingestions`와 GET 작업 조회는 COLLECT 및 설정 활성화된 COLLECT_AND_INDEX에 대해 구현됐다. 기존 동기 POST `/integrations/notion/connections/{connection_id}/resources`는 호환용 deprecated API이며 자체 자료 ID를 발급하므로 신규 통합에 사용하지 않는다. 기존 자료 ID는 자동 변경하지 않으며 Backend ID 이관은 별도 작업이다. 자료 삭제·진행 수집 취소도 구현됐다. COLLECT_AND_INDEX 청킹·임베딩·색인은 설정 활성화 후 사용할 수 있다. RAG 검색·답변은 RAG_ENABLED 활성화 후 사용할 수 있다. 설정·생성 모델·검증은 [검색·답변 안내](../architecture/retrieval-and-answers.md)를 따른다. 기존 Backend REGISTERED/EXTRACTING/INDEXING/READY 상태 및 URL 입력 명세도 기준 문서의 새 자료/작업 상태와 연결·페이지 선택 입력으로 변경해야 한다.

영속 큐·자동 복구·자동 동기화·파일·일반 웹페이지 지원은 후속 범위다. 기존 공개 URL/HTML 수집 명세를 현재 OAuth 경로와 병행 적용하지 않는다.
