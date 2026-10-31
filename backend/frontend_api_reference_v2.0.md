# 찾(Chaj) 서비스 — 프론트엔드 연동 API 레퍼런스 (MVP v2.0)

## 1. 개요

본 문서는 프론트엔드 개발팀이 현재 백엔드 API와 연동하기 위한 MVP v2.0 가이드입니다.

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

### [3.1] Resource API

| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/resources` | 공개 노션 URL 등록 및 비동기 처리 시작 | Yes |
| `GET` | `/api/v1/resources` | 현재 사용자가 등록한 자료 목록 조회 | Yes |
| `GET` | `/api/v1/resources/{resourceId}` | 특정 자료 상세 정보 및 처리 상태 조회 | Yes |
| `DELETE` | `/api/v1/resources/{resourceId}` | 자료 삭제 및 RAG 시스템에 관련 데이터 삭제 요청 | Yes |

### 3.1.1 자료 등록 요청

**`POST /api/v1/resources`**

Request Body:

```json
{
  "title": "프로젝트 참고 문서",
  "source": {
    "type": "URL",
    "url": "https://example.notion.site/reference-page"
  }
}
```

### Resource Status

- `REGISTERED`: 접수됨
- `EXTRACTING`: 본문 추출 중
- `INDEXING`: 임베딩 및 색인 중
- `READY`: 검색 및 RAG 답변 생성 가능
- `FAILED`: 처리 실패

> Resource는 Backend에서 관리하지만, Resource를 기반으로 생성되는 Chunk 및 Vector 데이터의 저장·검색은 RAG 시스템의 책임입니다.

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

### RAG 시스템

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
- Resource 등록 및 상태 표시
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
