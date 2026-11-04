# Notion 자료 로더 설계

2026-11-03 · OAuth 기반 수집. [Backend–AI 계약](backend-ai-contract.md)이 기준이다.

## 범위와 현재 구현

사용자가 OAuth로 연결한 워크스페이스에서 페이지를 선택하면 AI가 해당 연결의 토큰으로 Notion 공식 API를 호출한다. 공개 여부보다 연결의 접근 권한이 기준이다. 공개 URL 스크래핑, HTML 추출, 브라우저 렌더링을 전제로 한 2026-10-29 설계는 대체됐다.

현재 `app/adapters/outbound/notion/loader.py`의 `load_page(client, page_id)`가 페이지 정보와 Markdown을 조회해 `list[langchain_core.documents.Document]`를 반환한다. 현재 동기 등록은 `app/adapters/inbound/http/registration.py`에서 원본·본문·참조를 저장한다. COLLECT 비동기 접수·조회는 app/application/use_cases/ingestion.py와 app/adapters/inbound/http/ingestions.py에 구현돼 있다. 기존 동기 등록은 deprecated이며 COLLECT_AND_INDEX 청킹·임베딩·pgvector 저장도 구현됐다. 설정은 [색인 안내](indexing.md)를 따른다. 삭제 시 진행 중 수집은 CANCELLED가 되고 늦은 조회 결과를 저장하지 않는다.

## 수집·색인 흐름

```text
Backend: userId·resourceId·jobId·connectionId·pageId·operation 전달
AI: 소유권 확인 → 작업 등록 → 202 반환
  ↓ 접수 응답 후 같은 프로세스에서 비동기 실행 가능
NotionClient → load_page → NotionDocumentSource → TextDocument
  → 원본·본문·참조 저장 → EXTRACTED
  ├─ COLLECT: SUCCEEDED / 자료 COLLECTED
  └─ COLLECT_AND_INDEX: 청킹 → 임베딩 → 색인 공개
                         → SUCCEEDED / 자료 READY
```

직접 HTTP 호출은 동기 클라이언트이므로 목표 비동기 파이프라인에서는 스레드 등으로 실행해 이벤트 루프를 막지 않는다. 별도 워커·큐는 필수가 아니다. 청킹·임베딩은 로더 외부에서 담당하고 로더는 대화·벡터를 저장하지 않는다. 범용 로더 추상 클래스·선택기는 현재 필요하지 않다.

## Document와 저장 데이터

| 항목 | 의미 |
| --- | --- |
| page_content | 현재 페이지 Markdown. 제목·목록·표·체크박스·링크 보존 |
| metadata.page_id | Notion 원본 ID |
| metadata.title / source | 원문 제목·URL |
| metadata.last_edited_time / collected_at | 원문 수정·수집 UTC 시각 |
| metadata.sequence | 문서 내 구간 순서 |
| metadata.raw_content | API 원본 Markdown |
| metadata.references | 페이지·DB·미디어 참조 목록 |
| metadata.content_status / truncated / unknown_block_ids / warnings | 본문 완전성 진단 |

현재는 한 페이지를 Document 하나로 반환하며 raw_content와 page_content가 같다. 원본·검색용 본문 필드는 구분하되 정제는 아직 하지 않는다. 애플리케이션 경계에서는 자체 TextDocument로 변환한다. LangChain Document를 코어에 전달하지 않는다. 구체적인 계층은 [헥사고날 구조](hexagonal.md)를 따른다.

목표 저장 시 userId·resourceId는 Backend 요청에서 검증해 부여한다. 원본 문서에서 사용자·서비스 자료 ID를 읽지 않는다. 기존 AI 자체 UUID를 Backend 자료 ID로 자동 간주하지 않는다. 청크는 부모 resourceId와 출처 metadata를 보존한다.

## 참조 처리

`app/adapters/outbound/notion/references.py`는 Notion 확장 Markdown의 page/database/video 등 태그에서 참조를 추출한다. 현재 모든 일반 Markdown 링크를 페이지 참조로 해석하는 것은 아니다. 파싱된 페이지 참조의 can_register는 ID 해석 가능 여부이며 실제 접근 권한 보증이 아니다.

참조는 자동 수집하지 않는다. Frontend가 보여준 참조를 사용자가 선택할 때만 새 자료·작업으로 등록한다. 부모 소유권·같은 연결·실제 참조 여부를 확인하고 자식 접근 권한을 다시 확인한다. 자식 실패는 부모를 변경하지 않는다. 찾의 parentResourceId는 서비스 계층이며 Notion 계층 복제가 아니다.

DB 행, 하위 페이지 일괄 수집, 외부 임베드 내용, 첨부파일 본문·이미지 OCR은 제외한다. DB는 참조로만 표시한다. 참조를 따라가지 않았다는 이유로 부모를 partial로 표시하지 않는다.

본문 잘림·unknown 블록은 partial로 저장한다. COLLECT는 부분 본문을 진단용으로 보존할 수 있지만 색인은 CONTENT_INCOMPLETE로 실패한다. 빈 본문은 저장할 수 있고 색인 시 텍스트가 없으면 EMPTY_CONTENT다. `complete`와 `READY`는 다른 개념이다.

## 후속 범위

자동 동기화·Webhook·전체 워크스페이스 탐색·파일·일반 웹페이지 로더는 이후 확장한다. 작업 수명과 재시작 제약은 [API 계약](../api/references.md), 검증은 [검증 계획](../mvp-validation.md)을 따른다.
