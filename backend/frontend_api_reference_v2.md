# 찾(Chaj) 서비스 — 프론트엔드 연동 API 레퍼런스 (MVP v1.0)

## 1. 개요
본 문서는 프론트엔드 개발팀이 백엔드 API와 연동하기 위한 MVP v1.0 가이드입니다.
- **통신 규격**: `application/json`
- **인증 방식**: JWT Bearer 토큰 (`Authorization: Bearer <access_token>`)
- **식별자**: UUID (v4)
- **날짜 형식**: ISO 8601 (UTC 권장)
- **Base URL**: `http://localhost:8000` (개발 환경)

---

## 2. API 엔드포인트 상세 목록

### [2.1] 사용자 및 인증 (Auth & Users)
| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/signup` | 신규 사용자 회원가입 | No |
| `POST` | `/api/v1/auth/login` | 로그인 및 JWT 토큰(Access/Refresh) 발급 | No |
| `POST` | `/api/v1/auth/refresh` | Refresh Token을 이용한 Access Token 갱신 | No |
| `POST` | `/api/v1/auth/logout` | 로그아웃 (클라이언트 측 토큰 파기) | Yes |
| `GET` | `/api/v1/users/me` | 현재 로그인한 사용자 정보 조회 | Yes |

#### 1) 회원가입 요청 (`POST /api/v1/auth/signup`)
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```
- **Response (201 Created)**:
```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "email": "user@example.com"
}
```

#### 2) 로그인 요청 (`POST /api/v1/auth/login`)
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```
- **Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```

#### 3) 토큰 갱신 요청 (`POST /api/v1/auth/refresh`)
- **Request Body**:
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn..."
}
```
- **Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```

---

### [2.2] 자료 관리 (Resources - MVP: 공개 노션 URL)
| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/resources` | 공개 노션 페이지 URL 등록 및 비동기 처리 시작 | Yes |
| `GET` | `/api/v1/resources` | 현재 사용자가 등록한 자료 목록 조회 | Yes |
| `GET` | `/api/v1/resources/{resourceId}` | 특정 자료 상세 정보 및 처리 상태 조회 | Yes |
| `DELETE` | `/api/v1/resources/{resourceId}` | 자료 삭제 및 관련 RAG 데이터 삭제 요청 | Yes |

#### 1) 자료 등록 요청 (`POST /api/v1/resources`)
- **Request Body**:
```json
{
  "title": "프로젝트 참고 문서",
  "source": {
    "type": "URL",
    "url": "https://example.notion.site/reference-page"
  }
}
```
- **Resource Status 참고**:
  - `REGISTERED`: 접수됨
  - `EXTRACTING`: 본문 추출 중
  - `INDEXING`: 임베딩 및 색인 중
  - `READY`: 검색 및 RAG 답변 생성 가능 (준비 완료)
  - `FAILED`: 처리 실패

---

### [2.3] 대화 관리 (Messages)
| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/messages` | 현재 사용자의 대화 기록 조회 | Yes |
| `POST` | `/api/v1/messages` | 사용자 메시지 전송 및 AI 답변 생성 | Yes |
| `DELETE` | `/api/v1/messages` | 현재 사용자의 전체 대화 기록 초기화 | Yes |

#### 1) 메시지 전송 요청 (`POST /api/v1/messages`)
- **ConversationMode**: `GENERAL` (일반 대화) 또는 `RESOURCE` (자료 기반 RAG 대화)
- **Request Body**:
```json
{
  "mode": "RESOURCE",
  "message": "등록된 노션 페이지의 핵심 내용을 요약해줘.",
  "resourceIds": ["33333333-3333-4333-8333-333333333333"]
}
```
- **Response (200 OK)**:
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
      "locator": { "type": "URL", "url": "https://example.notion.site/reference-page" }
    }
  ]
}
```

---

### [2.4] 자료 검색 (Search)
| Method | Endpoint | 설명 | 인증 필요 |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/search` | 등록된 자료에서 관련 내용 검색 | Yes |

- **Request Body**:
```json
{
  "query": "RAG 검색의 역할",
  "resourceIds": ["33333333-3333-4333-8333-333333333333"],
  "topK": 5
}
```

---

## 3. 공통 에러 응답 형식
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
