# 찾(Chat) 서비스 — 프론트엔드 연동 API 레퍼런스 (MVP v2.1)

## 1. 개요

본 문서는 프론트엔드 개발팀이 현재 백엔드 API와 연동하기 위한 MVP v2.1 가이드입니다.

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

현재 Backend는 사용자가 등록한 자료(Resource)의 기본 정보와 처리 상태를 관리합니다.

**Chunk 데이터 자체는 Backend에서 관리하지 않으며, RAG 시스템에서 관리합니다.**

자료를 등록하려면 먼저 노션 연결([3.2])을 마쳐야 합니다. 연결 후 사용자가 노션 페이지 URL을 하나씩 입력해 등록합니다.

### [3.1] Resource API

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/resources` | 연결된 노션 페이지 URL 등록 및 비동기 처리 시작 | Yes |
| `GET` | `/api/v1/resources` | 현재 사용자가 등록한 자료 목록 조회 | Yes |
| `GET` | `/api/v1/resources/{resourceId}` | 특정 자료 상세 정보 및 처리 상태 조회 | Yes |
| `DELETE` | `/api/v1/resources/{resourceId}` | 자료 삭제 및 RAG 시스템에 관련 데이터 삭제 요청 | Yes |

### 3.1.1 자료 등록 요청

**`POST /api/v1/resources`**

Request Body:

```json
{
  "source": {
    "type": "NOTION_PAGE",
    "url": "https://www.notion.so/workspace/Project-Notes-0123456789abcdef0123456789abcdef"
  }
}
```

- `source.type`: `NOTION_PAGE`만 지원합니다.
- `source.url`: 노션 연결 때 사용자가 체크한 페이지 또는 그 하위 페이지의 주소입니다. 한 번에 하나만 등록합니다.
- Backend는 URL에서 노션 페이지 ID(32자리)를 추출하고, 사용자의 노션 연결 중 그 페이지를 읽을 수 있는 연결로 RAG 시스템에 등록을 요청합니다.
- 제목은 노션 페이지 제목을 사용하므로 요청에 포함하지 않습니다.

Response `202 Accepted`:

```json
{
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "title": null,
  "source": {
    "type": "NOTION_PAGE",
    "url": "https://www.notion.so/workspace/Project-Notes-0123456789abcdef0123456789abcdef"
  },
  "status": "REGISTERED",
  "error": null,
  "createdAt": "2026-11-02T10:00:00",
  "updatedAt": "2026-11-02T10:00:00"
}
```

- `title`: 본문 추출 전에는 `null`이며, 추출 후 노션 페이지 제목으로 채워집니다.
- `error`: `FAILED`일 때만 `code`, `message`를 포함하고 그 외에는 `null`입니다.

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `409` | `NOTION_NOT_CONNECTED` | 노션 연결이 없음. [3.2] 노션 연결 후 다시 시도 | `false` |
| `403` | `NOTION_PAGE_NOT_SHARED` | 노션 연결 때 체크하지 않은 페이지. 다시 연결해서 해당 페이지를 체크해야 함 | `false` |
| `409` | `RESOURCE_ALREADY_EXISTS` | 이미 등록한 노션 페이지 | `false` |
| `422` | `VALIDATION_ERROR` | 노션 페이지 주소가 아니거나 페이지 ID를 찾을 수 없음 | `false` |
| `502` | `RAG_SERVICE_UNAVAILABLE` | RAG 시스템 등록 요청 실패 | `true` |

### 3.1.2 자료 목록 조회 요청

**`GET /api/v1/resources`**

현재 사용자가 등록한 자료를 최근 등록 순으로 반환합니다.

Response `200 OK`:

```json
{
  "resources": [
    {
      "resourceId": "33333333-3333-4333-8333-333333333333",
      "title": "프로젝트 참고 문서",
      "source": {
        "type": "NOTION_PAGE",
        "url": "https://www.notion.so/workspace/Project-Notes-0123456789abcdef0123456789abcdef"
      },
      "status": "READY",
      "error": null,
      "createdAt": "2026-11-02T10:00:00",
      "updatedAt": "2026-11-02T10:01:00"
    }
  ]
}
```

### 3.1.3 자료 상세 조회 요청

**`GET /api/v1/resources/{resourceId}`**

Response `200 OK`: 3.1.2 목록의 항목 하나와 같은 형식입니다.

처리에 실패한 경우:

```json
{
  "resourceId": "33333333-3333-4333-8333-333333333333",
  "title": null,
  "source": {
    "type": "NOTION_PAGE",
    "url": "https://www.notion.so/workspace/Project-Notes-0123456789abcdef0123456789abcdef"
  },
  "status": "FAILED",
  "error": {
    "code": "EMPTY_CONTENT",
    "message": "색인할 본문이 없습니다."
  },
  "createdAt": "2026-11-02T10:00:00",
  "updatedAt": "2026-11-02T10:00:30"
}
```

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `RESOURCE_NOT_FOUND` | 존재하지 않거나 다른 사용자의 자료 | `false` |

### 3.1.4 자료 삭제 요청

**`DELETE /api/v1/resources/{resourceId}`**

Response `204 No Content` (응답 본문 없음)

Error Response는 3.1.3과 같습니다.

### Resource Status

- `REGISTERED`: 접수됨
- `EXTRACTING`: 본문 추출 중
- `INDEXING`: 임베딩 및 색인 중
- `READY`: 검색 및 RAG 답변 생성 가능
- `FAILED`: 처리 실패

Frontend는 `READY` 또는 `FAILED`가 될 때까지 `GET /api/v1/resources/{resourceId}`로 상태를 다시 조회합니다.

> Resource는 Backend에서 관리하지만, Resource를 기반으로 생성되는 Chunk 및 Vector 데이터의 저장·검색은 RAG 시스템의 책임입니다.

### [3.2] 노션 연결 (Notion Integration)

자료를 등록하기 전에 사용자의 노션 계정을 연결합니다. 사용자는 노션 화면에서 서비스가 읽을 페이지를 직접 체크하며, 체크한 페이지와 그 하위 페이지만 자료로 등록할 수 있습니다.

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/integrations/notion/authorize` | 노션 권한 허용 화면 주소 발급 | Yes |
| `GET` | `/api/v1/integrations/notion/connections` | 현재 사용자의 노션 연결 상태 조회 | Yes |
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

> **구현 필요 (Backend):** RAG 시스템의 콜백은 결과를 JSON으로 응답합니다. Backend 콜백이 이 결과를 받아 위 Frontend 주소로 이동시키고, RAG 시스템이 보낸 쿠키 삭제 헤더도 브라우저에 전달합니다. 중계 방식은 `ai/docs/api/notion-oauth.md`를 따릅니다.

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

- **ConversationMode**: `GENERAL` 또는 `RESOURCE`
- `GENERAL`: 일반 대화
- `RESOURCE`: 등록된 자료를 기반으로 하는 RAG 대화

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

- `resourceIds`: `RESOURCE` 모드에서는 1개 이상 필수이며, `GENERAL` 모드에서는 무시됩니다. 중복된 ID는 한 번만 처리됩니다.
- `citationId`: 답변 본문의 `[1]`, `[2]` 표시와 매칭되는 번호입니다. 답변마다 1부터 시작합니다.
- 사용자 메시지와 AI 답변은 답변 생성에 성공한 경우에만 대화 기록에 저장됩니다.

Error Response:

| Status | Code | 설명 | retryable |
| :--- | :--- | :--- | :--- |
| `404` | `RESOURCE_NOT_FOUND` | 존재하지 않거나 다른 사용자의 자료 (`details`에 해당 ID 포함) | `false` |
| `409` | `RESOURCE_NOT_READY` | `READY` 상태가 아닌 자료 포함 (`details`에 해당 ID 포함) | `true` |
| `422` | `VALIDATION_ERROR` | 잘못된 `mode`, 빈 `message`, `RESOURCE` 모드에서 `resourceIds` 누락 | `false` |
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
- 노션 페이지 URL에서 페이지 ID를 추출해 RAG 시스템에 등록 요청

### RAG 시스템

- 노션 연결(OAuth) 처리와 노션 토큰 암호화 보관
- 노션 공식 API로 페이지 본문 수집
- Resource 원문 기반 Chunk 생성
- Chunk 저장 및 관리
- Embedding 생성
- Vector 데이터 저장
- Vector Search / 관련 Chunk 검색
- RAG 답변 생성에 필요한 검색 데이터 관리

### Frontend

- 로그인 상태 및 토큰 관리
- 인증이 필요한 API 요청 시 Access Token 전달
- 로그인/로그아웃 UI 처리
- 노션 연결 단추와 연결 결과 화면 표시
- 노션 페이지 URL 입력, Resource 등록 및 상태 표시
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
노션 페이지 URL 하나 입력
  ↓
POST /api/v1/resources
  ↓
GET /api/v1/resources/{resourceId} 로 READY 확인
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

### v2.1

- 자료 등록을 공개 노션 URL 방식에서 노션 연결(OAuth) 후 페이지 URL 등록 방식으로 변경
- 노션 연결 API 추가: `POST /api/v1/integrations/notion/authorize`, `GET /api/v1/integrations/notion/connections`
- 노션 콜백 중계와 연결 후 돌아오는 Frontend 화면 규칙 추가
- 자료 등록 요청을 `source.type: NOTION_PAGE`로 변경하고 응답·오류 예시 추가
- 자료 목록·상세·삭제 응답 형식 추가
- 역할 구분, 공통 에러 응답, 연동 흐름에 노션 연결 반영

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
