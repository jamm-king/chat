# 찾 AI

Notion OAuth 연결, 공식 API 페이지 조회, 원본·본문·참조 저장을 담당한다. 수집·색인·검색으로 이어지는 목표 구조와 현재 구현을 구분해 문서를 읽는다.

| 문서 | 용도 |
| --- | --- |
| [헥사고날 코드 구조](docs/architecture/hexagonal.md) | 코어·포트·어댑터 경계와 의존성 조립 |
| [Backend–AI 연동 구조와 결정](docs/architecture/backend-ai-contract.md) | 역할·공통 ID·자료/작업 상태·참조·삭제 기준 |
| [현행 Notion OAuth 계약](docs/api/notion-oauth.md) | 구현된 OAuth API와 Backend 쿠키 중계 |
| [목표 API 계약](docs/api/references.md) | 비동기 수집·색인·검색·삭제 요청/응답 |
| [정적 OpenAPI](docs/api/openapi.json) | API v2.0.0, COLLECT·색인·삭제 구현, RAG 검색·답변은 목표 계약 |
| [로더 설계](docs/architecture/loader-architecture.md) | 현재 공식 API 로더와 참조 처리 |
| [검증 계획](docs/mvp-validation.md) | 현재 확인 항목과 구현 후 확인 항목 |

현재 실행 진입점은 `app.main:app`이며 `/docs`와 `/openapi.json`이 실제 구현 스키마다. OAuth·Notion 페이지 검색·미리보기와 COLLECT 비동기 접수·조회가 구현돼 있다. 기존 동기 자료 등록은 호환용 deprecated API다. 사용자별 자료 삭제·진행 작업 취소도 구현돼 있다. 청킹·OpenAI 임베딩·pgvector 저장과 COLLECT_AND_INDEX도 구현돼 있다. RAG 검색·답변 API는 아직 구현되지 않았다.

설정·실행은 [OAuth 문서](docs/api/notion-oauth.md#local-setup-and-verification)를 따른다. 기본 개발 DB는 Compose의 PostgreSQL 17 + pgvector다. 기존 볼륨의 확장 활성화 절차는 [색인 안내](docs/architecture/indexing.md#postgresql-준비)를 따른다.


## 비동기 수집 실행 확인

단일 프로세스로 실행한 `/docs`에서 서비스 토큰으로 인증 후 아래 요청을 호출한다.

```http
POST /internal/v1/ingestions
Content-Type: application/json
```

```json
{
  "jobId": "22222222-2222-4222-8222-222222222222",
  "userId": "로그인 사용자의 UUID",
  "resourceId": "Backend에서 발급한 새 자료 UUID",
  "connectionId": "해당 사용자의 Notion 연결 UUID",
  "pageId": "선택한 Notion 페이지 UUID",
  "parentResourceId": null,
  "operation": "COLLECT"
}
```

예시 문자열은 실제 UUID로 교체한다. 202의 Location 또는 `GET /internal/v1/ingestions/{jobId}?userId={userId}`로 조회하고 SUCCEEDED/FAILED에서 폴링을 끝낸다. COLLECT 성공은 resourceStatus=COLLECTED, result.ready=false다. 저장한 문서는 기존 `GET /integrations/notion/resources/{resourceId}?userId={userId}`로 확인할 수 있다.

INGESTION_TIMEOUT_SECONDS는 기본 600초다. 작업 상태는 메모리에 있고 재시작 후 404 JOB_NOT_FOUND로 사라지지만 문서·완료 색인은 DB에 유지된다. 자동 재시도는 하지 않는다. COLLECT_AND_INDEX는 INDEXING_ENABLED=true와 OpenAI 키·pgvector 준비 후 사용할 수 있다. 비활성 시 409 OPERATION_NOT_AVAILABLE이다. 취소·삭제는 아래 DELETE API로 수행한다. 색인 실패 후에도 본문은 보존하므로 PROCESSING/FAILED 자료 상태와 최신 오류는 Backend가 작업 응답으로 반영해야 한다. 기존 자료 컬럼·ID는 유지하고 색인 완료 레코드·청크 테이블을 시작 시 추가 생성한다.


## 자료 삭제·취소 확인

```http
DELETE /internal/v1/resources/{resourceId}?userId={userId}
Authorization: Bearer <AI_SERVICE_TOKEN>
```

성공은 본문 없는 204다. 삭제한 자료는 목록에서 제외되고 기존 자료 조회는 404다. 진행 중 작업을 조회하면 CANCELLED/DELETED와 RESOURCE_DELETED 오류가 반환된다. 부모 삭제는 자식까지 삭제하지 않으며 parent_resource_id를 null로 바꾼다. 물리 삭제 실패(503)·기한 초과(504)는 Backend에서 검색 제외를 유지하고 명시적으로 재시도해야 한다. 완료 작업의 과거 성공 결과로 DELETED 자료를 복원하면 안 된다.

삭제 표시는 메모리에만 남으므로 단일 프로세스에서 사용한다. 재시작·삭제 실패에 관한 제약은 [API 계약](docs/api/references.md#현재-삭제-구현과-제약)을 따른다.


## 청킹·임베딩·색인 활성화

기본 모델은 text-embedding-3-small, 1536차원이다. `.env.example`의 INDEXING_ENABLED·OPENAI_API_KEY·EMBEDDING_MODEL 등 설정과 PostgreSQL의 pgvector 확장을 준비해야 한다. 설치·활성화·테스트 방법은 [색인 안내](docs/architecture/indexing.md)를 따른다. 기본값 false에서는 기존 수집·OAuth 기능을 계속 사용할 수 있다.
