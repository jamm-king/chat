# Backend–AI 연동 구조와 확정 계약

2026-11-05 · COLLECT 접수·조회와 자료 삭제·작업 취소 구현. COLLECT_AND_INDEX 색인과 RAG 검색·답변도 구현됐다. 각각 설정 활성화가 필요하다.

## 문서 적용 범위

이 문서는 Notion OAuth 기반 자료 등록·수집·색인·검색의 기준이다. 공개 Notion URL 스크래핑을 전제로 한 기존 설계와, 본문 수집 완료를 검색 준비 완료로 처리하는 해석을 대체한다.

- 현재 OAuth API와 쿠키 중계: [Notion OAuth](../api/notion-oauth.md)
- 비동기·검색·답변 API: [API 계약](../api/references.md), [정적 OpenAPI](../api/openapi.json)
- 현재 구현의 정확한 HTTP 스키마: 실행 중 AI 서버의 `/openapi.json`

정적 OpenAPI는 구현된 수집·색인·삭제·RAG 계약을 함께 표시하며 런타임 OpenAPI와 동일하지 않다. Backend 통합 시 프론트 명세·DB 모델도 아래 상태·입력·ID 정책과 대조한다.

## 1. 책임과 현재 구현

| 주체 | 책임 |
| --- | --- |
| Frontend | Backend 로그인, Notion 연결·페이지 선택, 등록·상태 표시 |
| Backend | 로그인 사용자 확인, 자료 소유권·검색 범위 검증, 자료·작업 ID 발급, AI 요청·상태 반영, 대화·출처 스냅샷 보존 |
| AI | Notion OAuth·토큰 암호화 저장, 연결 소유권 재검증, 공식 API 수집, 작업 실행, 청킹·임베딩·검색·답변 |

Frontend는 Backend만 호출한다. `AI_SERVICE_TOKEN`과 Notion 토큰은 Frontend에 전달하지 않는다. AI의 `userId`는 서비스 토큰으로 인증된 Backend가 실제 로그인 사용자로부터 결정한다. 두 서비스는 서로의 DB에 직접 접근하지 않는다.

| 기능 | 현재 코드 | 목표 계약 |
| --- | --- | --- |
| OAuth | AI 처리 및 Backend 쿠키·콜백 중계 구현 | 현행 유지 |
| 페이지 선택 | AI 검색·미리보기 구현 | Backend 경유 UI 연결 |
| 수집·저장 | 공통 자료 ID로 COLLECT 비동기 접수·저장, HTTP 202 | 구현됨. 기존 HTTP 201 동기 경로는 deprecated |
| 작업 API | COLLECT·COLLECT_AND_INDEX 메모리 작업 조회·종료 결과 제공 | 재시작 복구 제외 |
| 청킹·임베딩·벡터 저장 | COLLECT_AND_INDEX 구현 (설정 시 활성화) | 색인 커밋 후에만 READY |
| RAG 검색·답변 | GENERAL·RESOURCE 및 AUTO 도구 선택 답변 (RAG_ENABLED) | 범위·삭제 재검증, 실제 모델 품질 평가 필요 |
| AI 자료 삭제 | 원본·본문·참조·청크·벡터·색인 완료 레코드 삭제 구현 | 수집·색인 중 삭제 시 늦은 결과 공개 방지 |

현재 AI의 `content_status: complete`는 현재 페이지 본문의 API 응답 기준 완전성을 뜻한다. 검색 가능한 상태나 참조 자료 수집 완료를 뜻하지 않는다. `status: connected`도 저장된 연결 표시이며 현재 토큰 유효성을 검사한 결과가 아니다.

## 2. OAuth: 기존 쿠키 중계 유지

```text
Frontend → Backend: POST /api/v1/integrations/notion/authorize (사용자 인증)
Backend → AI: POST /integrations/notion/authorize {userId} + 서비스 토큰
AI → Backend → Browser: authorization_url + Set-Cookie
Browser → Notion: 승인
Browser → Backend callback: code/state + OAuth 쿠키
Backend → AI callback: code/state/error + 해당 OAuth 쿠키만 전달
AI: state·브라우저 확인 → 토큰 교환·암호화 저장
Backend: 쿠키 삭제 헤더 전달 → 고정 Frontend 결과 화면으로 303 이동
Frontend → Backend → AI: 사용자별 연결 목록 조회
```

쿠키 중계와 결과 화면 이동은 `backend/app/routers/notion.py`에 구현돼 있다. 별도 일회용 시작 URL 기능은 필수가 아니며 현재 명세에 추가하지 않는다. 단순히 인증 URL만 중계하고 `Set-Cookie`를 누락하면 인증에 실패한다. 개발 환경에서는 브라우저 시작 주소와 콜백의 호스트를 `localhost`로 통일한다.

사용자별 여러 연결을 허용한다. 현재 재인증 갱신 키는 `(user_id, workspace_id, bot_id)`다. 워크스페이스 이름이나 사용자 이메일로 연결을 구분하지 않는다. Notion 연결 권한은 Read content만 허용하는 구성이 기준이다. 현재 OAuth URL은 별도의 scope 파라미터를 보내지 않으므로 실제 연결 권한 설정도 확인해야 한다. 페이지 클라이언트는 읽기 작업만 사용한다.

## 3. 자료 선택과 공통 식별자

사용자는 연결과 페이지를 선택한다. Frontend 입력은 `connectionId`, `pageId`, 선택적인 `parentResourceId`다. URL 입력·여러 연결 순회로 읽기 가능한 연결을 추측하는 방식은 기본 등록 흐름에서 제외한다. 원본 URL은 AI가 조회한 출처 metadata로 저장한다.

- `userId`: Backend 로그인 사용자 ID. AI가 사용자 범위를 재검증하는 기준.
- `resourceId`: Backend가 발급하며 AI 저장·검색·삭제·답변 출처에서도 같은 값 사용.
- `jobId`: Backend가 작업마다 새로 발급. 자료 ID와 별개.
- `connectionId`: AI가 OAuth 연결 시 발급. 자료 등록에 사용한 연결을 명시.
- `pageId`: Notion 원본 페이지 ID. 서비스 자료 ID와 별개.
- `parentResourceId`: 기존 부모 자료의 resourceId. 찾 서비스 계층이며 Notion 원본 계층을 그대로 복제하지 않음.
- `chunkId`·`answerId`: AI가 각각 청크 저장·답변 생성 시 발급. Backend는 출처·답변 스냅샷과 함께 보관한다.
- `X-Request-Id`: Backend가 전달하거나 AI가 생성하는 요청 추적 UUID. 멱등성 키가 아니다.

목표 구조에서는 `ai_resource_id`를 별도 저장하지 않는다. 기존 동기 경로에서 AI 자체 ID로 저장한 자료는 Backend 공통 ID로 이관하거나 재등록하는 전환 작업이 필요하다. 현재 UUID를 자동으로 Backend ID와 동일하다고 간주하면 안 된다.

## 4. 비동기 작업과 완료 의미

Backend는 자료를 PROCESSING으로 만들고 AI에 작업을 요청한다. AI는 최소 입력·연결 소유권·ID 충돌을 검사하고 작업을 등록한 뒤, Notion 조회나 임베딩을 기다리지 않고 `202`를 반환한다. 현재 동기 API의 응답 코드만 202로 바꾸는 것은 이 계약의 구현이 아니다.

| operation | 처리 | 정상 종료 결과 |
| --- | --- | --- |
| COLLECT | 선택한 한 페이지의 원본·본문·참조 저장 | 작업 SUCCEEDED, 자료 COLLECTED, ready=false |
| COLLECT_AND_INDEX | 수집 후 청킹·임베딩·색인 공개 | 작업 SUCCEEDED, 자료 READY, ready=true |

현재 COLLECT와 COLLECT_AND_INDEX가 구현돼 있다. 색인 설정 비활성 상태의 COLLECT_AND_INDEX 요청은 `409 OPERATION_NOT_AVAILABLE`로 거절하며 본문 저장만으로 성공 처리하지 않는다.

### 자료 상태

| 상태 | 의미 |
| --- | --- |
| PROCESSING | 실행·대기 중인 작업이 있음 |
| COLLECTED | 본문 저장 완료, 검색 가능한 색인은 없음 |
| READY | 색인 완료·검색 가능 |
| FAILED | 요청한 처리 실패 |
| DELETED | 사용자 조회·검색 대상에서 제외 |

COLLECTED는 수집만 끝난 자료를 PROCESSING이나 READY로 오인하지 않도록 추가한 상태다. Frontend는 현재 작업이 종료되면 폴링을 멈추고 COLLECTED 자료에는 검색 준비 전임을 표시한다.

### 작업 상태

```text
COLLECT:           QUEUED → EXTRACTING → EXTRACTED → SUCCEEDED
COLLECT_AND_INDEX: QUEUED → EXTRACTING → EXTRACTED → INDEXING → SUCCEEDED
진행 상태에서 FAILED 또는 CANCELLED로 종료 가능
```

EXTRACTED는 수집 단계를 통과했다는 진행 상태이고 작업의 종료 상태가 아니다. Backend/Frontend의 폴링 종료 기준은 SUCCEEDED, FAILED, CANCELLED다. COLLECT 성공을 기다리며 READY를 폴링하면 안 된다.

기존 COLLECTED 자료에 같은 원본 식별자로 새 COLLECT_AND_INDEX 작업을 요청하면 보존한 본문 스냅샷을 사용해 `QUEUED → EXTRACTING → EXTRACTED → INDEXING → SUCCEEDED`로 진행한다. EXTRACTING에서 저장된 스냅샷을 읽으며 Notion 원문을 자동 재수집하지 않는다. 이 승격은 색인 설정 활성화 시 지원한다. 자료의 원본 식별자 변경은 새 resourceId로 등록한다.

AI가 작업 실행 상태의 기준이다. Backend는 jobId에 맞는 결과를 저장·전달하고 이미 삭제한 자료를 늦은 성공 응답으로 되살리지 않는다. 오류는 AI 작업 결과의 `code`, `message`, `retryable`을 Backend 작업 레코드에 보관한다. 자료 상세 응답의 error는 최근 작업 오류에서 만든다.

자동 검색 판단을 사용하려면 Backend는 /internal/v1/answers에 mode=AUTO와 명시적인 resourceIds를 보낸다. 기존 GENERAL·RESOURCE의 의미는 유지한다. AUTO의 응답 mode는 검색 도구 호출 여부에 따라 GENERAL 또는 RESOURCE이며 Backend가 질문을 의미 분류하지 않는다. 자료 범위의 소유권·READY 검증은 계속 Backend와 AI가 담당한다.

## 5. 참조와 사용자 선택 등록

원본 Markdown과 본문을 보존하고 페이지·DB·미디어 참조를 별도로 저장한다. 현재 구현의 raw_content와 content는 동일하며 별도 정제는 아직 하지 않는다.

- 등록 요청 한 번은 선택한 페이지 한 개만 수집한다. 참조를 자동 재귀 수집하지 않는다.
- 참조만 남아 있다는 이유로 부모 본문을 partial 처리하지 않는다. 본문 잘림·unknown 블록 등은 별도 진단으로 유지한다.
- Frontend가 참조 목록을 보여주고, 사용자가 추가 등록을 선택하면 Backend가 새 resourceId·jobId를 발급하고 기존 부모 resourceId를 함께 전달한다.
- 부모 소유권, 같은 연결, 실제 페이지 참조 여부를 확인한 뒤 선택한 자식 페이지의 현재 접근 권한을 확인한다. 자식 등록 실패는 부모를 실패로 만들지 않는다.
- DB는 참조로만 표시한다. 행 수집, 외부 영상 내용, 첨부파일 본문·OCR은 제외한다.
- `can_register`는 해석 가능한 페이지 참조라는 뜻이며 Notion 접근 권한 보증이 아니다. 등록 시 재검증한다.

## 6. 저장·조회·삭제 책임

| Backend DB | AI DB |
| --- | --- |
| 사용자·자료 소유권, 공통 resourceId | 사용자·연결별 암호화한 Notion 토큰 |
| connectionId·pageId·parentResourceId | 공통 resourceId별 원본·본문·참조·출처 |
| 자료 상태, 최신 작업 ID·작업 오류 | 청크·임베딩·색인 완료 정보 |
| 대화·답변·출처 스냅샷 | 검색·답변 생성에 필요한 데이터 |

Backend의 자료는 서비스 관리 레코드이고 AI의 notion_resources는 수집 스냅샷이다. AI DB는 notion_connections·notion_resources·notion_chunks·notion_resource_indexes의 네 테이블을 사용한다. 작업 상태와 삭제 제외 표시는 DB가 아닌 프로세스 메모리에 둔다.

삭제 시 Backend는 먼저 DELETED로 표시하고 검색 요청 범위에서 제외한다. AI 삭제 API는 진행 작업을 취소하고 검색을 차단한 뒤 원본·본문·참조·청크·벡터를 삭제한다. 검색 차단을 해제하거나 삭제 자료를 다시 공개하지 않는다. 반복 삭제는 204이며 다른 사용자의 데이터는 변경하지 않는다.

AI 삭제 실패는 Backend에 표시하고 검색 제외를 유지한다. Backend 소프트 삭제만 적용한 경우 AI 데이터의 물리 삭제까지 완료됐다고 안내하지 않는다. 부모 자료 삭제는 그 자료에만 적용하고 자식은 독립 자료로 유지하며 부모 연결을 해제한다. 자동 하위 자료 삭제는 하지 않는다.

과거 답변의 출처는 Backend에 저장한 제목·URL·발췌 스냅샷으로 보존한다. 현재 AI 자료가 존재해야만 과거 출처를 표시할 수 있는 구조로 만들지 않는다.

## 7. 통합 검증 순서와 제외 범위

1. 현재 OAuth 쿠키 중계·사용자별 연결·페이지 선택을 통합 검증한다.
2. Backend 공통 resourceId로 COLLECT 비동기 접수·상태 조회가 연결되는지 확인한다.
3. 명시적 참조 선택 등록과 삭제·검색 제외 계약을 연결한다.
4. 구현된 COLLECT_AND_INDEX·검색·답변을 실제 키·고정 자료로 통합 검증한다. 색인과 RAG는 설정 활성화가 필요하다.

영속 큐·별도 워커·자동 재시도·재시작 복구·Webhook·자동 동기화는 후속이다. 초기 비동기 실행은 AI 단일 프로세스와 메모리 작업 상태를 사용할 수 있다. 재시작 후 작업 조회가 404이면 Backend는 작업 유실을 기록하고 폴링을 중단하며 자동 재접수하지 않는다. 이미 저장된 자료·연결은 유지한다.
