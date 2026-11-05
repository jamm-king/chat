# 찾(Chat) 서비스 — 프론트엔드 연동 API 레퍼런스 (MVP v2.4)

## 1. 개요

본 문서는 프론트엔드 개발팀이 현재 백엔드 API와 연동하기 위한 MVP v2.4 가이드입니다.

- **통신 규격**: `application/json`
- **인증 방식**: JWT Bearer 토큰 (`Authorization: Bearer <access_token>`)
- **식별자**: UUID (v4)
- **날짜 형식**: ISO 8601 (UTC 권장)
- **Base URL**: `http://localhost:8000`

### 1.1 인증 토큰 관리

로그인 성공 시 Backend는 Access Token과 Refresh Token을 함께 발급합니다.

- **Access Token**: 인증이 필요한 API 요청에 사용
- **Refresh Token**: Access Token 갱신에 사용
- **로그아웃**: Backend에서 해당 Refresh Token을 revoke 처리하고, Frontend에서는 Access Token과 Refresh Token을 삭제
- 로그아웃 후에도 기존 Access Token은 만료되기 전까지 유효할 수 있으므로 Frontend에서는 로그아웃 시 토큰을 반드시 삭제해야 합니다.

인증이 필요한 API 요청:

```http
Authorization: Bearer <access_token>
```

---

## 2. API 엔드포인트 상세 목록

### [2.1] 사용자 및 인증 (Auth & Users)

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/signup` | 신규 사용자 회원가입 | No |
| `POST` | `/api/v1/auth/login` | 로그인 및 Access/Refresh Token 발급 | No |
| `POST` | `/api/v1/auth/refresh` | Refresh Token을 이용한 토큰 갱신 | No |
| `POST` | `/api/v1/auth/logout` | 로그아웃 및 Refresh Token 폐기 | No |
| `GET` | `/api/v1/users/me` | 현재 로그인한 사용자 정보 조회 | Yes |

> **Logout 참고:** 현재 API는 Refresh Token을 요청 Body로 전달받아 서버에서 해당 Refresh Token을 revoke 처리합니다. 이후 Frontend에서 보관 중인 Access Token과 Refresh Token을 삭제해야 합니다.

### 2.1.1 회원가입 요청

**`POST /api/v1/auth/signup`**

Request Body:

```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

Response `201 Created`:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "email": "user@example.com"
}
```

### 2.1.2 로그인 요청

**`POST /api/v1/auth/login`**

Request Body:

```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

Response `200 OK`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```

### 2.1.3 토큰 갱신 요청

**`POST /api/v1/auth/refresh`**

Request Body:

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn..."
}
```

Response `200 OK`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```

> Refresh Token Rotation을 사용합니다. 토큰 갱신에 성공하면 기존 Refresh Token은 폐기되고 새로운 Refresh Token이 발급됩니다. Frontend는 응답으로 받은 새로운 Refresh Token으로 기존 값을 교체해야 합니다.

### 2.1.4 현재 사용자 조회

**`GET /api/v1/users/me`**

Request Header:

```http
Authorization: Bearer <access_token>
```

Response `200 OK`:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "email": "user@example.com"
}
```

### 2.1.5 로그아웃

**`POST /api/v1/auth/logout`**

Request Body:

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn..."
}
```

로그아웃 처리:

1. Backend에서 전달받은 Refresh Token을 검증합니다.
2. 해당 Refresh Token을 DB에서 revoke 처리합니다.
3. Frontend에서는 Access Token과 Refresh Token을 삭제합니다.

---

## 3. 자료 관리 (Resources)

Backend는 사용자가 등록한 자료(Resource)의 기본 정보, 처리 상태, 최근 처리 작업(Job)을 관리합니다. 노션 본문 수집·청크·임베딩·검색은 RAG 시스템이 담당합니다.

자료를 등록하려면 먼저 노션 연결([3.2])을 마쳐야 합니다. 사용자는 연결을 고르고, 그 연결에서 페이지를 검색해 선택한 뒤([3.2.4]) 한 번에 한 페이지씩 등록합니다.

### [3.1] Resource API

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/resources` | 선택한 노션 페이지 등록, 수집 작업 접수 | Yes |
| `GET` | `/api/v1/resources` | 현재 사용자가 등록한 자료 목록 조회 | Yes |
| `GET` | `/api/v1/resources/{resourceId}` | 특정 자료 상세 및 처리 상태 조회 (처리 중이면 최신 상태로 갱신) | Yes |
| `DELETE` | `/api/v1/resources/{resourceId}` | 자료 삭제 및 RAG 시스템에 관련 데이터 삭제 요청 | Yes |

### 자료 응답 형식 (Resource 객체)

등록·목록·상세 응답은 모두 아래 형식의 Resource 객체를 사용합니다.

```json
{
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "title": "프로젝트 회의록",
  "source": {
    "type": "NOTION_PAGE",
    "connectionId": "66666666-6666-4666-8666-666666666666",
    "pageId": "55555555-5555-4555-8555-555555555555",
    "url": "https://www.notion.so/55555555555545558555555555555555"
  },
  "parentResourceId": null,
  "status": "COLLECTED",
  "job": {
    "jobId": "22222222-2222-4222-8222-222222222222",
    "operation": "COLLECT",
    "status": "SUCCEEDED"
  },
  "error": null,
  "createdAt": "2026-11-03T01:00:00Z",
  "updatedAt": "2026-11-03T01:00:03Z"
}
```

| 필드 | 설명 |
| :--- | :--- |
| `resourceId` | Backend가 발급한 자료 ID. RAG 시스템도 같은 ID를 사용합니다. |
| `title` | 노션 페이지 제목. 수집이 끝나기 전에는 `null`입니다. |
| `source.type` | `NOTION_PAGE`만 지원합니다. |
| `source.connectionId` | 등록에 사용한 노션 연결 ID ([3.2.3]) |
| `source.pageId` | 노션 페이지 ID ([3.2.4]) |
| `source.url` | 노션 원본 주소. 수집이 끝나기 전에는 `null`입니다. |
| `parentResourceId` | 다른 자료의 참조 페이지로 등록한 경우 부모 자료 ID. 최상위 자료는 `null`입니다. |
| `status` | 자료 상태 (아래 Resource Status) |
| `job` | 최근 처리 작업. `operation`은 `COLLECT`(수집만) 또는 `COLLECT_AND_INDEX`(수집+색인), `status`는 아래 Job Status |
| `error` | `FAILED`일 때만 `{ "code", "message", "retryable" }`, 그 외에는 `null` |

### Resource Status

| 상태 | 의미 | Frontend 표시 |
| :--- | :--- | :--- |
| `PROCESSING` | 처리 작업이 대기 또는 실행 중 | 처리 중 표시, 상세 조회로 폴링 |
| `COLLECTED` | 본문 수집 완료, 검색 준비 전 (색인 없음) | "수집 완료 · 검색 준비 전" 표시. 대화(RESOURCE 모드)에는 아직 사용할 수 없음 |
| `READY` | 색인 완료, 검색 및 RAG 답변에 사용 가능 | 대화에서 선택 가능 |
| `FAILED` | 처리 실패 | `error.message` 표시, `retryable`이면 다시 등록 안내 |

### Job Status

`QUEUED` → `EXTRACTING` → `EXTRACTED` → (`INDEXING`) → `SUCCEEDED`, 또는 도중에 `FAILED` / `CANCELLED`로 끝납니다. `EXTRACTED`는 진행 중 상태이며 종료 상태가 아닙니다.

**폴링 규칙:** 자료 `status`가 `PROCESSING`인 동안 `GET /api/v1/resources/{resourceId}`를 2~10초 간격으로 조회하고, `COLLECTED`·`READY`·`FAILED`가 되면 멈춥니다. `COLLECTED`가 된 자료에 대해 `READY`를 기다리며 계속 폴링하지 않습니다.

> Backend는 등록할 때 `COLLECT_AND_INDEX`(수집+색인)를 먼저 요청합니다. RAG 시스템의 색인 설정이 꺼져 있으면 `COLLECT`(수집만)로 다시 요청하며, 이때 자료는 `COLLECTED`에서 멈추고 `READY`가 되지 않습니다. 어떤 작업으로 접수됐는지는 `job.operation`으로 확인할 수 있습니다.

### 3.1.1 자료 등록 요청

**`POST /api/v1/resources`**

Request Body:

```json
{
  "connectionId": "66666666-6666-4666-8666-666666666666",
  "pageId": "55555555-5555-4555-8555-555555555555",
  "parentResourceId": null
}
```

- `connectionId`: [3.2.3] 연결 목록의 `connectionId`
- `pageId`: [3.2.4] 페이지 검색 결과의 `pageId`
- `parentResourceId`: 선택. 이미 등록한 자료의 참조 페이지를 추가로 등록할 때 부모 자료 ID. 최상위 자료는 생략하거나 `null`
- 제목·URL은 노션에서 가져오므로 요청에 포함하지 않습니다.
- 한 번에 한 페이지만 등록하며, 참조 페이지를 자동으로 함께 등록하지 않습니다.

Response `202 Accepted`: Resource 객체

```json
{
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "title": null,
  "source": {
    "type": "NOTION_PAGE",
    "connectionId": "66666666-6666-4666-8666-666666666666",
    "pageId": "55555555-5555-4555-8555-555555555555",
    "url": null
  },
  "parentResourceId": null,
  "status": "PROCESSING",
  "job": {
    "jobId": "22222222-2222-4222-8222-222222222222",
    "operation": "COLLECT",
    "status": "QUEUED"
  },
  "error": null,
  "createdAt": "2026-11-03T01:00:00Z",
  "updatedAt": "2026-11-03T01:00:00Z"
}
```

- 등록 요청은 작업 접수만 하고 바로 응답합니다. 본문 수집은 응답 후 진행되므로 위 폴링 규칙으로 상태를 확인합니다.
- 노션 페이지 접근 권한은 수집 단계에서 확인됩니다. 권한 문제는 등록 응답이 아니라 이후 `FAILED` 자료의 `error.code`로 확인합니다 (아래 처리 실패 코드).

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `NOTION_CONNECTION_NOT_FOUND` | 존재하지 않거나 다른 사용자의 노션 연결 | `false` |
| `404` | `RESOURCE_NOT_FOUND` | `parentResourceId`에 해당하는 자료가 없음 | `false` |
| `409` | `RESOURCE_ALREADY_EXISTS` | 같은 연결에서 이미 등록한 노션 페이지 | `false` |
| `409` | `INVALID_PARENT_REFERENCE` | 부모 자료와 다른 연결이거나, 부모 페이지가 참조하는 페이지가 아님 | `false` |
| `422` | `VALIDATION_ERROR` | 필수 값 누락, ID 형식 오류 | `false` |
| `502` | `RAG_SERVICE_UNAVAILABLE` | RAG 시스템 작업 접수 실패 | `true` |

처리 실패 코드 (`FAILED` 자료의 `error.code`):

| Code | 설명 | retryable |
| :--- | :--- | :--- |
| `NOTION_ACCESS_DENIED` | 노션 연결에 이 페이지 읽기 권한이 없음. 노션 연결 때 페이지를 체크해야 함 | `false` |
| `NOTION_PAGE_NOT_FOUND` | 페이지가 삭제되었거나 연결에 공유되지 않음 (노션은 두 경우를 구분하지 않음) | `false` |
| `NOTION_REAUTHORIZATION_REQUIRED` | 노션 권한이 만료됨. [3.2] 노션을 다시 연결해야 함 | `false` |
| `JOB_LOST` | RAG 시스템 재시작 등으로 처리 작업이 사라짐. 다시 등록 필요 | `true` |
| 그 외 | RAG 시스템이 전달한 코드와 메시지를 그대로 표시 | 응답값 따름 |

### 3.1.2 자료 목록 조회 요청

**`GET /api/v1/resources`**

현재 사용자가 등록한 자료를 최근 등록 순으로 반환합니다. 삭제한 자료는 포함하지 않습니다.

Response `200 OK`:

```json
{
  "resources": [
    { "resourceId": "...", "title": "프로젝트 회의록", "status": "COLLECTED", "...": "Resource 객체" }
  ]
}
```

- 목록 조회는 저장된 상태를 그대로 반환합니다. 처리 중인 자료의 최신 상태는 상세 조회(3.1.3)로 확인합니다.

### 3.1.3 자료 상세 조회 요청

**`GET /api/v1/resources/{resourceId}`**

Response `200 OK`: Resource 객체

- 자료가 `PROCESSING`이면 Backend가 RAG 시스템에 작업 상태를 확인해 최신 상태로 갱신한 뒤 반환합니다.
- RAG 시스템에 일시적으로 연결할 수 없으면 마지막으로 저장된 상태(`PROCESSING`)를 그대로 반환합니다. 폴링을 계속하면 됩니다.

처리에 실패한 경우:

```json
{
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "title": null,
  "source": {
    "type": "NOTION_PAGE",
    "connectionId": "66666666-6666-4666-8666-666666666666",
    "pageId": "55555555-5555-4555-8555-555555555555",
    "url": null
  },
  "parentResourceId": null,
  "status": "FAILED",
  "job": {
    "jobId": "22222222-2222-4222-8222-222222222222",
    "operation": "COLLECT",
    "status": "FAILED"
  },
  "error": {
    "code": "NOTION_ACCESS_DENIED",
    "message": "노션 연결에 이 페이지를 읽을 권한이 없습니다.",
    "retryable": false
  },
  "createdAt": "2026-11-03T01:00:00Z",
  "updatedAt": "2026-11-03T01:00:02Z"
}
```

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `RESOURCE_NOT_FOUND` | 존재하지 않거나, 다른 사용자의 자료이거나, 삭제한 자료 | `false` |

### 3.1.4 자료 삭제 요청

**`DELETE /api/v1/resources/{resourceId}`**

Response `204 No Content` (응답 본문 없음)

- 삭제한 자료는 즉시 목록·상세·대화 검색 대상에서 제외됩니다.
- 진행 중인 처리 작업은 취소됩니다.
- 이 자료를 부모로 등록한 자료는 삭제되지 않고 독립 자료로 남습니다.
- 과거 대화 답변의 출처는 그대로 남습니다.

Error Response는 3.1.3과 같습니다.

> Resource는 Backend에서 관리하지만, Resource를 기반으로 생성되는 Chunk 및 Vector 데이터의 저장·검색은 RAG 시스템의 책임입니다.

### [3.2] 노션 연결 (Notion Integration)

자료를 등록하기 전에 사용자의 노션 계정을 연결합니다. 사용자는 노션 화면에서 서비스가 읽을 페이지를 직접 체크하며, 체크한 페이지와 그 하위 페이지만 자료로 등록할 수 있습니다.

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/integrations/notion/authorize` | 노션 권한 허용 화면 주소 발급 | Yes |
| `GET` | `/api/v1/integrations/notion/connections` | 현재 사용자의 노션 연결 상태 조회 | Yes |
| `GET` | `/api/v1/integrations/notion/connections/{connectionId}/pages` | 연결된 노션에서 등록할 페이지 검색 | Yes |
| `GET` | `/integrations/notion/callback` | 노션 허용 후 브라우저가 돌아오는 Backend 주소. RAG 시스템에 전달한 뒤 Frontend 화면으로 이동 (Frontend가 직접 호출하지 않음) | No |

### 3.2.1 권한 허용 주소 발급

**`POST /api/v1/integrations/notion/authorize`**

Request Body: 없음

Response `200 OK`:

```json
{
  "authorizationUrl": "https://api.notion.com/v1/oauth/authorize?client_id=...&response_type=code&owner=user&redirect_uri=...&state=..."
}
```

- Frontend는 현재 창을 `authorizationUrl`로 이동합니다.
- 사용자는 노션 화면에서 등록할 페이지를 체크하고 허용합니다.
- 주소는 발급 후 10분 동안 한 번만 사용할 수 있습니다.
- 응답에는 연결 확인용 쿠키(`notion_oauth_browser`, HttpOnly)가 함께 오며 브라우저가 자동으로 저장합니다. Frontend 코드에서 읽거나 저장하지 않습니다.
- 다른 출처(origin)에서 호출할 때는 `fetch`에 `credentials: "include"`가 필요합니다. 개발 환경의 Vite 프록시(`/api`)를 쓰면 같은 출처라 필요 없습니다.
- 권한 허용은 주소를 받은 같은 브라우저에서 진행하고, 한 브라우저에서 두 연결을 동시에 진행하지 않습니다.
- 개발 환경에서는 `localhost`로 접속합니다. `127.0.0.1`과 섞으면 쿠키가 전달되지 않습니다.

### 3.2.2 연결 후 돌아오는 Frontend 화면

노션 화면에서 허용하거나 취소하면 브라우저는 Backend 콜백(`http://localhost:8000/integrations/notion/callback`)을 거쳐 아래 Frontend 주소로 이동합니다. (개발 환경 기준)

```text
http://localhost:5173/notion/callback?status=connected
http://localhost:5173/notion/callback?status=failed&reason=denied
```

| reason | 뜻 |
| :--- | :--- |
| `denied` | 사용자가 노션 화면에서 취소함 |
| `expired` | 권한 허용 주소의 유효 시간(10분)이 지났거나, 이미 사용했거나, 다른 브라우저에서 진행함 |
| `failed` | 노션 토큰 발급 또는 저장 실패 |

> RAG 시스템의 콜백 결과를 Backend가 받아 위 Frontend 주소로 이동시키고, 쿠키 삭제 헤더도 브라우저에 전달합니다. (구현됨, 중계 방식은 `ai/docs/api/notion-oauth.md`) 주소의 `status`만으로 연결을 확정하지 말고, 돌아온 뒤 [3.2.3] 연결 목록을 다시 조회해 확인합니다.

### 3.2.3 연결 상태 조회

**`GET /api/v1/integrations/notion/connections`**

Response `200 OK`:

```json
{
  "connections": [
    {
      "connectionId": "66666666-6666-4666-8666-666666666666",
      "workspaceName": "My Workspace",
      "status": "CONNECTED",
      "createdAt": "2026-11-02T10:00:00"
    }
  ]
}
```

- `connections`가 비어 있으면 연결 전입니다. Frontend는 `노션 연결` 단추를 표시합니다.
- 한 사용자가 여러 노션 워크스페이스를 연결할 수 있습니다. 같은 워크스페이스를 다시 연결하면 기존 연결이 갱신됩니다.
- `status`는 저장된 연결이라는 뜻이며, 노션 권한이 지금도 유효한지는 확인하지 않습니다.

### 3.2.4 노션 페이지 검색

**`GET /api/v1/integrations/notion/connections/{connectionId}/pages`**

Query Parameters:

| 이름 | 필수 | 설명 |
| :--- | :--- | :--- |
| `query` | No | 페이지 제목 검색어 (최대 1000자). 생략하면 최근 페이지 순 |
| `startCursor` | No | 다음 페이지를 받을 때 이전 응답의 `nextCursor` |
| `pageSize` | No | 한 번에 받을 개수, 1~100, 기본 50 |

Response `200 OK`:

```json
{
  "pages": [
    {
      "pageId": "55555555-5555-4555-8555-555555555555",
      "title": "프로젝트 회의록",
      "url": "https://www.notion.so/55555555555545558555555555555555",
      "lastEditedTime": "2026-11-02T09:00:00Z"
    }
  ],
  "hasMore": false,
  "nextCursor": null
}
```

- 노션 연결 때 사용자가 체크한 페이지(와 그 하위 페이지) 중에서 제목으로 검색합니다. 노션 검색 특성상 접근 가능한 모든 페이지가 빠짐없이 나온다는 보장은 없습니다.
- 휴지통·보관된 페이지는 제외합니다.
- 결과의 `pageId`를 [3.1.1] 자료 등록 요청에 사용합니다.

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `NOTION_CONNECTION_NOT_FOUND` | 존재하지 않거나 다른 사용자의 노션 연결 | `false` |
| `409` | `NOTION_REAUTHORIZATION_REQUIRED` | 노션 권한 만료. [3.2] 노션을 다시 연결해야 함 | `false` |
| `429` | `NOTION_RATE_LIMITED` | 노션 요청 한도 초과. 잠시 후 다시 시도 | `true` |
| `502` | `RAG_SERVICE_UNAVAILABLE` | RAG 시스템 또는 노션 응답 실패 | `true` |

---

## 4. 대화 관리 (Messages)

### [4.1] Message API

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/messages` | 현재 사용자의 대화 기록 조회 | Yes |
| `POST` | `/api/v1/messages` | 사용자 메시지 전송 및 AI 답변 생성 | Yes |
| `DELETE` | `/api/v1/messages` | 현재 사용자의 전체 대화 기록 초기화 | Yes |

### 4.1.1 메시지 전송 요청

**`POST /api/v1/messages`**

- **mode** (선택, 기본값 `AUTO`): `GENERAL`, `RESOURCE`, `AUTO`
- `GENERAL`: 일반 대화. 자료를 검색하지 않음
- `RESOURCE`: 등록된 자료를 기반으로 하는 RAG 대화
- `AUTO`: RAG 시스템이 질문을 보고 `GENERAL`과 `RESOURCE` 중 하나를 판단함. `mode`를 생략하면 `AUTO`

`mode`를 적어 보내면 Backend는 그 값을 그대로 RAG 시스템에 전달합니다. 응답과 대화 기록의 `mode`는 판단이 끝난 값(`GENERAL` 또는 `RESOURCE`)이며 `AUTO`는 나오지 않습니다.

| 요청 | 의미 | RAG 시스템에 전달하는 자료 |
| :--- | :--- | :--- |
| `GENERAL` | 자료 없이 대화 | 없음 (`resourceIds`를 보내도 무시) |
| `RESOURCE` + `resourceIds` | 고른 자료를 기준으로 답변 | 고른 자료 |
| `AUTO` + `resourceIds` | 고른 자료를 참고하되, 자료가 필요한 질문인지는 RAG 시스템이 판단 | 고른 자료 |
| `AUTO` (자료 선택 없음, 또는 `mode` 생략) | 자료 필요 여부와 범위를 RAG 시스템이 판단 | 사용자의 `READY` 자료 전체 |

- `resourceIds`는 [3.1.2] 자료 목록의 `resourceId`입니다. 사용자가 채팅 화면에서 자료를 골랐을 때 보냅니다.
- `RESOURCE`와 `AUTO`에서 보낸 `resourceIds`는 같은 규칙으로 검사합니다 (본인 자료인지, `READY`인지). 아래 Error Response 참고.

> **AUTO 모드는 RAG 시스템 쪽 구현이 진행 중입니다 (2026-11-05 기준, 계약 문서 확정 전).** 위 표의 "`AUTO` (자료 선택 없음) → `READY` 자료 전체 전달"과 "응답 `mode`에 판단 결과가 담겨 온다"는 Backend의 가정이며, RAG 시스템 계약(`ai/docs/api/references.md` 3장)이 확정되면 이 문서를 맞춰 고칩니다.

Request Body:

```json
{
  "mode": "RESOURCE",
  "message": "등록된 노션 페이지의 핵심 내용을 요약해줘.",
  "resourceIds": [
    "33333333-3333-4333-8333-333333333333"
  ]
}
```

`AUTO` 예시 (`mode`를 생략해도 같음):

```json
{
  "mode": "AUTO",
  "message": "지난 회의에서 정한 마감일이 언제야?"
}
```

Response `200 OK`:

```json
{
  "answerId": "55555555-5555-4555-8555-555555555555",
  "mode": "RESOURCE",
  "status": "ANSWERED",
  "content": "노션 페이지의 핵심 요약은 다음과 같습니다.[1]",
  "citations": [
    {
      "citationId": "1",
      "resourceId": "33333333-3333-4333-8333-333333333333",
      "title": "프로젝트 참고 문서",
      "excerpt": "핵심 내용 발췌 텍스트...",
      "locator": {
        "type": "URL",
        "url": "https://example.notion.site/reference-page"
      }
    }
  ]
}
```

> Citation은 프론트엔드에서 AI 답변의 출처를 표시하기 위한 데이터입니다. Backend에 Chunk 테이블이 없어지더라도 프론트엔드는 `resourceId`, `title`, `excerpt`, `locator` 등을 이용하여 출처를 표시할 수 있습니다.

- `mode`: 판단이 끝난 대화 방식 (`GENERAL` 또는 `RESOURCE`). `AUTO`로 요청했다면 RAG 시스템이 고른 값입니다.
- `resourceIds`: `RESOURCE` 모드에서는 1개 이상 필수, `AUTO` 모드에서는 선택, `GENERAL` 모드에서는 무시됩니다. 중복된 ID는 한 번만 처리됩니다.
- `citationId`: 답변 본문의 `[1]`, `[2]` 표시와 매칭되는 번호입니다. 답변마다 1부터 시작합니다.
- `status`: 답변 결과입니다. 세 값 모두 `200 OK`이며 `content`에 화면에 보여줄 문장이 들어 있습니다.

| status | 의미 | citations |
| :--- | :--- | :--- |
| `ANSWERED` | 답변 완료 | 응답 `mode`가 `GENERAL`이면 없음, `RESOURCE`면 1개 이상 |
| `INSUFFICIENT_EVIDENCE` | 응답 `mode`가 `RESOURCE`인데 자료에 질문의 근거가 부족함. 일반 지식으로 대신 답하지 않음 | 없음 |
| `REFUSED` | 안전 정책에 따라 답변을 거절함 | 없음 |

- `INSUFFICIENT_EVIDENCE`·`REFUSED`도 정상 응답이라 대화 기록에 저장됩니다. 화면에서는 오류가 아닌 안내 문구로 보여주면 됩니다. (대화 기록 조회 응답에는 `status`가 없습니다.)
- 답변 생성은 최대 1분 정도 걸릴 수 있습니다. 요청 중에는 로딩 상태를 보여주고 같은 질문을 중복 전송하지 않게 해주세요.
- 사용자 메시지와 AI 답변은 답변 생성에 성공한 경우에만 대화 기록에 저장됩니다.

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `RESOURCE_NOT_FOUND` | 존재하지 않거나 다른 사용자의 자료 (`details`에 해당 ID 포함) | `false` |
| `409` | `RESOURCE_NOT_READY` | `READY` 상태가 아닌 자료 포함 (`details`에 해당 ID 포함) | `true` |
| `422` | `VALIDATION_ERROR` | `GENERAL`·`RESOURCE`·`AUTO`가 아닌 `mode`, 빈 `message`, `RESOURCE` 모드에서 `resourceIds` 누락 | `false` |
| `502` | `RAG_SERVICE_UNAVAILABLE` | RAG 시스템 답변 생성 실패 | `true` |

### 4.1.2 대화 기록 조회 요청

**`GET /api/v1/messages`**

현재 사용자의 대화 기록을 오래된 순으로 반환합니다.

Response `200 OK`:

```json
{
  "messages": [
    {
      "messageId": "44444444-4444-4444-8444-444444444444",
      "role": "USER",
      "mode": "RESOURCE",
      "content": "등록된 노션 페이지의 핵심 내용을 요약해줘.",
      "citations": [],
      "createdAt": "2026-11-01T06:00:00"
    },
    {
      "messageId": "55555555-5555-4555-8555-555555555555",
      "role": "ASSISTANT",
      "mode": "RESOURCE",
      "content": "노션 페이지의 핵심 요약은 다음과 같습니다.[1]",
      "citations": [
        {
          "citationId": "1",
          "resourceId": "33333333-3333-4333-8333-333333333333",
          "title": "프로젝트 참고 문서",
          "excerpt": "핵심 내용 발췌 텍스트...",
          "locator": {
            "type": "URL",
            "url": "https://example.notion.site/reference-page"
          }
        }
      ],
      "createdAt": "2026-11-01T06:00:00"
    }
  ]
}
```

- `role`: `USER` 또는 `ASSISTANT`
- AI 답변의 `messageId`는 메시지 전송 응답의 `answerId`와 같습니다.
- `createdAt`은 UTC 기준입니다.

### 4.1.3 대화 기록 초기화 요청

**`DELETE /api/v1/messages`**

현재 사용자의 모든 메시지와 출처(Citation) 기록을 삭제합니다.

Response `204 No Content` (응답 본문 없음)

---

## 5. 자료 검색 (Search)

### [5.1] Search API

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/search` | 등록된 자료를 기반으로 관련 내용 검색 | Yes |

Request Body:

```json
{
  "query": "RAG 검색의 역할",
  "resourceIds": [
    "33333333-3333-4333-8333-333333333333"
  ],
  "topK": 5
}
```

> 검색 대상인 Chunk와 Vector 데이터는 RAG 시스템에서 관리합니다. Frontend는 Chunk 테이블이나 Chunk 저장 구조를 직접 알 필요가 없습니다.

---

## 6. Backend와 RAG 시스템의 역할 구분

현재 시스템의 데이터 책임은 다음과 같이 구분합니다.

### Backend

- 사용자 회원가입 / 로그인 / 로그아웃
- Access Token / Refresh Token 관리
- 사용자 인증 및 권한 확인
- Resource 기본 정보 관리
- Resource 처리 상태 관리
- Message 및 대화 기록 관리
- Frontend와 RAG 시스템 사이의 API 연동
- 노션 연결 요청 중계 (권한 허용 주소 발급, 콜백 전달과 Frontend 화면 이동, 연결 상태 조회)
- 자료 ID·작업 ID 발급, 노션 페이지 검색 중계, RAG 시스템에 수집 작업 요청과 작업 상태 반영
- 메시지의 `mode` 전달 (생략 시 `AUTO`), `AUTO`일 때 검색 가능한 자료 범위(`READY` 자료) 전달, 판단된 `mode`로 대화 기록 저장

### RAG 시스템

- 노션 연결(OAuth) 처리와 노션 토큰 암호화 보관
- 노션 공식 API로 페이지 본문 수집
- Resource 원문 기반 Chunk 생성
- Chunk 저장 및 관리
- Embedding 생성
- Vector 데이터 저장
- Vector Search / 관련 Chunk 검색
- RAG 답변 생성에 필요한 검색 데이터 관리
- `AUTO` 모드에서 질문이 일반 대화인지 자료 기반 대화인지 판단

### Frontend

- 로그인 상태 및 토큰 관리
- 인증이 필요한 API 요청 시 Access Token 전달
- 로그인/로그아웃 UI 처리
- 노션 연결 단추와 연결 결과 화면 표시
- 노션 연결·페이지 선택, Resource 등록 및 상태 표시 (처리 중 폴링)
- 대화 UI 표시
- AI 답변 및 Citation 표시

> **중요:** Frontend는 Backend DB의 `chunk` 테이블이나 RAG 내부 저장 구조에 직접 접근하지 않습니다.

---

## 7. 공통 인증 요청

인증이 필요한 모든 API는 다음 Header를 사용합니다.

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

예:

```http
GET /api/v1/users/me
Authorization: Bearer eyJhbGciOiJIUzI1NiIsIn...
```

---

## 8. 공통 에러 응답 형식

에러 발생 시 아래와 같은 형식으로 응답됩니다.

```json
{
  "error": {
    "code": "RESOURCE_NOT_READY",
    "message": "Requested resources are not ready.",
    "retryable": false,
    "details": []
  },
  "requestId": "77777777-7777-4777-8777-777777777777"
}
```

- RAG 시스템에서 받은 오류도 Backend가 이 형식으로 바꿔 전달합니다.

---

## 9. Frontend 연동 시 핵심 사항

### 로그인

```text
POST /api/v1/auth/login
        ↓
Access Token + Refresh Token 수신
        ↓
Frontend에 토큰 저장
        ↓
인증 API 요청 시 Access Token 사용
```

### Access Token 만료

```text
API 요청
  ↓
Access Token 만료
  ↓
Refresh Token으로 /auth/refresh 요청
  ↓
새 Access Token + 새 Refresh Token 수신
  ↓
Frontend에서 기존 토큰 교체
  ↓
기존 요청 재시도
```

### 로그아웃

```text
Frontend
  ↓
POST /api/v1/auth/logout
  ↓
Backend에서 Refresh Token revoke
  ↓
Frontend에서 Access Token / Refresh Token 삭제
  ↓
로그인 화면으로 이동
```

### 노션 연결과 자료 등록

```text
GET /api/v1/integrations/notion/connections
  ↓
연결 없음 → POST /api/v1/integrations/notion/authorize
  ↓
authorizationUrl로 이동 → 노션 화면에서 페이지 체크 후 허용
  ↓
Backend 콜백(/integrations/notion/callback) → RAG 시스템에 전달
  ↓
/notion/callback?status=connected 로 돌아옴
  ↓
GET /api/v1/integrations/notion/connections 로 연결 확인
  ↓
GET /api/v1/integrations/notion/connections/{connectionId}/pages?query=... 로 페이지 검색·선택
  ↓
POST /api/v1/resources { connectionId, pageId } → 202, status PROCESSING
  ↓
GET /api/v1/resources/{resourceId} 를 2~10초 간격으로 조회
  ↓
COLLECTED(수집 완료, 검색 준비 전) / READY(대화 사용 가능) / FAILED 에서 폴링 종료
```

### RAG 자료 검색

```text
Frontend
  ↓
Backend API
  ↓
RAG 시스템
  ↓
Chunk / Vector 검색
  ↓
검색 결과 및 RAG 답변
  ↓
Backend
  ↓
Frontend
```

---

## 10. 버전 변경 사항

### v2.4

- 자료 API 구현 ([3.1]): 등록 시 `COLLECT_AND_INDEX`를 먼저 요청하고, 색인이 꺼져 있으면 `COLLECT`로 요청
- 메시지 전송 `mode`에 `AUTO` 추가, `mode`를 생략하면 `AUTO` ([4.1.1])
- `AUTO`는 RAG 시스템이 `GENERAL`/`RESOURCE`를 판단하고, 응답·대화 기록의 `mode`는 판단된 값으로 반환
- `AUTO`에서 `resourceIds`는 선택. 없으면 Backend가 사용자의 `READY` 자료 전체를 전달 (RAG 시스템 계약 확정 전 가정)

### v2.3

- 메시지 답변이 임시 답변에서 RAG 시스템의 실제 답변으로 바뀜 (`POST /internal/v1/answers` 연동)
- 메시지 전송 응답 `status`에 `INSUFFICIENT_EVIDENCE`, `REFUSED` 추가 ([4.1.1])

### v2.2

- AI 확정 계약(`ai/docs/architecture/backend-ai-contract.md`)에 맞춰 자료 등록을 비동기 작업 방식으로 변경
- 자료 등록 입력을 노션 URL에서 `connectionId` + `pageId` (+ `parentResourceId`)로 변경
- 자료 상태를 `PROCESSING` / `COLLECTED` / `READY` / `FAILED`로 변경하고 작업(`job`) 정보와 폴링 규칙 추가
- 자료 응답에 `source.connectionId`, `source.pageId`, `parentResourceId`, `job`, `error.retryable` 추가
- 등록 오류 코드 정리 (`NOTION_NOT_CONNECTED`, `NOTION_PAGE_NOT_SHARED` 제거 → 연결 오류는 `NOTION_CONNECTION_NOT_FOUND`, 페이지 권한 문제는 처리 실패 코드로 이동)
- 노션 페이지 검색 API 추가: `GET /api/v1/integrations/notion/connections/{connectionId}/pages`
- v2.1의 "동기 처리로 응답 시점에 READY일 수 있음" 안내 삭제

### v2.1

- 자료 등록을 공개 노션 URL 방식에서 노션 연결(OAuth) 후 페이지 URL 등록 방식으로 변경
- 노션 연결 API 추가: `POST /api/v1/integrations/notion/authorize`, `GET /api/v1/integrations/notion/connections`
- 노션 콜백 중계와 연결 후 돌아오는 Frontend 화면 규칙 추가
- 자료 등록 요청을 `source.type: NOTION_PAGE`로 변경하고 응답·오류 예시 추가
- 자료 목록·상세·삭제 응답 형식 추가
- 역할 구분, 공통 에러 응답, 연동 흐름에 노션 연결 반영
- 자료 등록이 현재 동기 처리되어 응답 시점에 `READY`일 수 있다는 점과 등록 중 로딩 표시 안내 추가

### v2.0

- JWT 로그인/인증 흐름 최신화
- Access Token / Refresh Token 구조 반영
- Refresh Token Rotation 반영
- Logout 시 Refresh Token revoke 처리 반영
- `/api/v1/users/me` 인증 방식 반영
- Backend에서 Chunk 테이블 제거
- Chunk 관련 Backend FK 제거
- Chunk 및 Vector 데이터 관리 책임을 RAG 시스템으로 분리
- Resource 삭제 시 RAG 시스템의 관련 데이터 삭제 요청으로 역할 명확화
- Search API의 Chunk 검색 책임을 RAG 시스템으로 명시
- Frontend의 토큰 관리 및 로그아웃 처리 방식 명확화
