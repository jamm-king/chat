# 찾 AI

Notion OAuth 연결, 공식 API 페이지 조회, 원본·본문·참조 저장을 담당한다. 수집·색인·검색으로 이어지는 목표 구조와 현재 구현을 구분해 문서를 읽는다.

| 문서 | 용도 |
| --- | --- |
| [Backend–AI 연동 구조와 결정](docs/architecture/backend-ai-contract.md) | 역할·공통 ID·자료/작업 상태·참조·삭제 기준 |
| [현행 Notion OAuth 계약](docs/api/notion-oauth.md) | 구현된 OAuth API와 Backend 쿠키 중계 |
| [목표 API 계약](docs/api/references.md) | 비동기 수집·색인·검색·삭제 요청/응답 |
| [정적 OpenAPI](docs/api/openapi.json) | API v2.0.0, COLLECT·삭제 구현, 색인·검색은 목표 계약 |
| [로더 설계](docs/architecture/loader-architecture.md) | 현재 공식 API 로더와 참조 처리 |
| [검증 계획](docs/mvp-validation.md) | 현재 확인 항목과 구현 후 확인 항목 |

현재 실행 진입점은 `app.main:app`이며 `/docs`와 `/openapi.json`이 실제 구현 스키마다. OAuth·Notion 페이지 검색·미리보기와 COLLECT 비동기 접수·조회가 구현돼 있다. 기존 동기 자료 등록은 호환용 deprecated API다. 사용자별 자료 삭제·진행 작업 취소도 구현돼 있다. 임베딩·RAG 검색·COLLECT_AND_INDEX는 아직 구현되지 않았다.

설정·실행은 [OAuth 문서](docs/api/notion-oauth.md#local-setup-and-verification)를 따른다. DB는 Windows에 직접 설치한 PostgreSQL을 사용할 수 있으며 Docker는 선택 사항이다.


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

INGESTION_TIMEOUT_SECONDS는 기본 600초다. 작업 상태는 메모리에 있고 재시작 후 404 JOB_NOT_FOUND로 사라지지만 완료된 문서는 DB에 유지된다. 자동 재시도는 하지 않는다. COLLECT_AND_INDEX는 아직 409 OPERATION_NOT_AVAILABLE이다. 취소·삭제는 아래 DELETE API로 수행한다. 현재 작업은 성공 문서만 DB에 저장하므로 PROCESSING/FAILED 자료 상태와 최신 오류는 Backend가 작업 응답으로 반영해야 한다. DB 스키마 변경은 없다.


## 자료 삭제·취소 확인

```http
DELETE /internal/v1/resources/{resourceId}?userId={userId}
Authorization: Bearer <AI_SERVICE_TOKEN>
```

성공은 본문 없는 204다. 삭제한 자료는 목록에서 제외되고 기존 자료 조회는 404다. 진행 중 작업을 조회하면 CANCELLED/DELETED와 RESOURCE_DELETED 오류가 반환된다. 부모 삭제는 자식까지 삭제하지 않으며 parent_resource_id를 null로 바꾼다. 물리 삭제 실패(503)·기한 초과(504)는 Backend에서 검색 제외를 유지하고 명시적으로 재시도해야 한다. 완료 작업의 과거 성공 결과로 DELETED 자료를 복원하면 안 된다.

삭제 표시는 메모리에만 남으므로 단일 프로세스에서 사용한다. 재시작·삭제 실패에 관한 제약은 [API 계약](docs/api/references.md#현재-삭제-구현과-제약)을 따른다.
