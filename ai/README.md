# 찾 AI

Notion OAuth 연결, 공식 API 페이지 조회, 원본·본문·참조 저장을 담당한다. 수집·색인·검색으로 이어지는 목표 구조와 현재 구현을 구분해 문서를 읽는다.

| 문서 | 용도 |
| --- | --- |
| [Backend–AI 연동 구조와 결정](docs/architecture/backend-ai-contract.md) | 역할·공통 ID·자료/작업 상태·참조·삭제 기준 |
| [현행 Notion OAuth 계약](docs/api/notion-oauth.md) | 구현된 OAuth API와 Backend 쿠키 중계 |
| [목표 API 계약](docs/api/references.md) | 비동기 수집·색인·검색·삭제 요청/응답 |
| [정적 OpenAPI](docs/api/openapi.json) | 목표 API v2.0.0, 아직 서버 구현을 의미하지 않음 |
| [로더 설계](docs/architecture/loader-architecture.md) | 현재 공식 API 로더와 참조 처리 |
| [검증 계획](docs/mvp-validation.md) | 현재 확인 항목과 구현 후 확인 항목 |

현재 실행 진입점은 `app.main:app`이며 `/docs`와 `/openapi.json`이 실제 구현 스키마다. OAuth·Notion 페이지 검색·미리보기·동기 자료 등록은 구현돼 있고, 목표 비동기 작업·임베딩·RAG 검색·삭제 API는 아직 구현되지 않았다.

설정·실행은 [OAuth 문서](docs/api/notion-oauth.md#local-setup-and-verification)를 따른다. DB는 Windows에 직접 설치한 PostgreSQL을 사용할 수 있으며 Docker는 선택 사항이다.
