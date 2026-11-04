# 청킹·임베딩·색인

2026-11-04 · COLLECT_AND_INDEX 구현. RAG 검색·답변도 구현됐으며 [실행 안내](retrieval-and-answers.md)를 따른다.

## 동작

`POST /internal/v1/ingestions`에 operation=COLLECT_AND_INDEX를 전달한다. INDEXING_ENABLED=true일 때 접수되며, 꺼져 있으면 409 OPERATION_NOT_AVAILABLE다. 모델·DB 설정을 확인하지 않은 상태에서 COLLECT를 READY로 취급하지 않는다.

```text
QUEUED → EXTRACTING → EXTRACTED → INDEXING → SUCCEEDED / READY
```

같은 userId·resourceId·connectionId·pageId로 이미 COLLECTED 문서가 있으면 저장한 스냅샷을 사용한다. 원문을 다시 조회하지 않는다. 새 jobId만 발급하고 원래 자료 ID는 유지한다. 이미 READY이면 RESOURCE_ALREADY_INDEXED이며 모델 설정만 바꿔도 자동 재색인하지 않는다. 현재 모델·차원을 바꿔 재등록하려면 기존 자료 삭제 후 새 자료 ID로 등록한다. 전용 재색인 API는 후속이다.

원본·본문·참조는 먼저 보존한다. 청크 생성·외부 임베딩이 모두 끝난 후 한 DB 트랜잭션으로 모든 청크·벡터와 완료 레코드를 저장한다. 이 커밋 이후에만 작업 ready=true / resourceStatus=READY다. 실패한 임베딩 또는 DB 쓰기로 일부 색인만 공개하지 않는다. 실패 시 본문 스냅샷은 남아 새 작업으로 색인을 재시도할 수 있다.

현재 자원 조회의 resource_status는 저장된 색인 상태(COLLECTED/READY)다. 진행·실패 여부는 최신 jobId의 작업 응답으로 확인하고 Backend 자료 상태에 반영한다. 진행 중이거나 실패한 작업을 완료된 검색 준비 상태로 해석하지 않는다.

## 기본 설정

| 환경변수 | 기본값 | 의미 |
| --- | --- | --- |
| INDEXING_ENABLED | false | 색인 활성화. 수집·OAuth는 비활성 상태에서도 사용 가능 |
| OPENAI_API_KEY | 없음 | OpenAI 서버용 키. 로그·Frontend에 노출하지 않음 |
| EMBEDDING_MODEL | text-embedding-3-small | 현재 지원: text-embedding-3-small / text-embedding-3-large |
| EMBEDDING_DIMENSIONS | 1536 | small 최대 1536, large 최대 3072 |
| EMBEDDING_BATCH_SIZE | 32 | 호출당 청크 수, 최대 32 |
| EMBEDDING_TIMEOUT_SECONDS | 30 | 외부 호출 타임아웃, 자동 재시도 없음 |
| CHUNK_SIZE | 1000 | 문자 수 기준, 64~2000 |
| CHUNK_OVERLAP | 150 | 문자 수 기준, chunk size보다 작아야 함 |

기본 모델은 비용 중심으로 선택했다. 2026-11-04 공식 가격 기준 small은 입력 100만 토큰당 $0.02, large는 $0.13이다. 청크 중첩으로 같은 본문이 반복되면 실제 임베딩 입력량도 증가한다. [OpenAI small 모델](https://developers.openai.com/api/docs/models/text-embedding-3-small), [large 모델](https://developers.openai.com/api/docs/models/text-embedding-3-large), [임베딩 가이드](https://developers.openai.com/api/docs/guides/embeddings).

LangChain RecursiveCharacterTextSplitter로 문단·줄·문장·공백 순서의 경계를 우선한다. 원문 본문은 수정하지 않으며 청크에는 제목·URL·Notion 페이지 ID·순서·문자 시작 위치를 남긴다. 전체 원본·참조 목록을 청크마다 복사하지 않는다. 한국어도 문자 수로 분할하며 토큰 수와 문자 수를 같은 값으로 보지 않는다.

임베딩은 `langchain_openai.OpenAIEmbeddings.embed_documents`로 호출한다. 직접 HTTP 요청·응답을 구성하지 않는다. 모델·차원·배치 수·타임아웃을 전달하고 `max_retries=0`으로 자동 재시도를 끈다. 이미 문자 단위로 분할한 청크가 추가 분할·평균화되지 않도록 `check_embedding_ctx_length=False`를 사용한다. 현재 청크 크기는 최대 2000자다. httpx는 LangChain/OpenAI SDK의 HTTP 전송과 앱 종료 시 연결 정리를 위해 주입한다. [LangChain 공식 연동 문서](https://docs.langchain.com/oss/python/integrations/embeddings/openai).

부분 본문은 CONTENT_INCOMPLETE, 빈 텍스트는 EMPTY_CONTENT로 색인을 거절한다. 페이지·DB 참조는 수집하지 않고 원래 본문에 존재하는 텍스트만 분할한다. 입력 순서에 대응하는 벡터 반환은 LangChain에 맡기고, 반환된 벡터의 개수·차원·유한 수치·0이 아닌 값을 검사한다. 공급자 오류·키·응답 원문은 노출하지 않는다. 작업 상태·취소는 애플리케이션 유스케이스가 관리하고 최종 DB 트랜잭션은 저장소 어댑터가 담당한다. 청킹·임베딩은 LangChain 어댑터가 구현하며 코어는 자체 TextDocument와 포트만 사용한다. [코드 구조](hexagonal.md)를 따른다.

## PostgreSQL 준비

Python pgvector 패키지는 DB 서버에 확장을 설치하지 않는다. `ai/compose.yaml`은 확장 파일이 포함된 `pgvector/pgvector:pg17`을 사용한다. 기존 PostgreSQL 17과 같은 메이저 버전·볼륨을 유지한다. Docker Desktop 실행 후 `ai`에서 다음을 실행한다.

```sh
docker compose up -d --wait db
docker compose exec db psql -U postgres -d find_ai -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec db psql -U postgres -d find_ai -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

새 볼륨은 `docker/postgres/init/001-vector.sql`로 확장을 자동 활성화한다. 기존 볼륨에서는 초기화 스크립트가 다시 실행되지 않으므로 위 SQL 명령이 필요하다. 확장 활성화를 위해 볼륨을 삭제하지 않는다. 기존 볼륨은 원래 사용자·비밀번호·DB 이름으로 접속한다. 다른 PostgreSQL 서버가 5432 포트를 사용 중이면 먼저 실행 대상을 정리한다. Windows 직접 설치를 유지하려면 [Windows 설치 안내](https://github.com/pgvector/pgvector#windows)에 따라 확장을 별도 설치해야 한다.

그다음 의존성을 `python -m pip install -e ".[test]"`로 갱신하고 .env에 실제 키를 입력한 뒤 INDEXING_ENABLED=true로 바꿔 단일 프로세스로 재시작한다. 확장이 활성화되지 않았으면 색인 활성화 시 시작 오류로 안내한다. 수집만 실행할 때는 false를 유지하면 된다. 테스트용 SQLite를 실제 pgvector의 대체로 간주하지 않는다.

새 테이블은 시작 시 생성하며 기존 notion_resources 컬럼·자료 ID를 변경하지 않는다.

| 테이블 | 저장 데이터 |
| --- | --- |
| notion_resource_indexes | 완료 자료 ID·사용자, 모델·차원, 청크 수·크기·중첩·분할 버전, 색인 시각 |
| notion_chunks | 청크 ID·사용자·자료 ID·순서·본문·출처 metadata·pgvector 벡터 |

벡터 컬럼은 모델 차원 변경을 수용하며 각 완료 레코드에 실제 차원과 모델을 기록한다. 검색 구현 시 다른 모델 공간·차원의 벡터를 섞어 비교하면 안 된다. 현재 대규모 ANN/HNSW 인덱스는 만들지 않는다. 현재 검색 API는 사용자·모델·차원 범위로 제한한 코사인 거리 검색을 수행한다. 성능 최적화는 이후 단계다.

## 취소·삭제·검증

삭제와 최종 색인 커밋은 같은 잠금으로 조율한다. 삭제·시간 초과 후 늦게 끝난 임베딩은 공개하지 않는다. 배치 사이에도 취소·기한을 확인한다. 이미 전송한 외부 API 호출의 과금·전송을 취소하는 보장은 없으며, 다음 배치와 저장을 중단한다. 자료 삭제는 원본·본문·참조뿐 아니라 해당 청크·벡터·완료 레코드도 제거한다.

기본 자동 테스트는 LangChain/OpenAI SDK를 거치는 모의 HTTP 응답·SQLite 저장과 PostgreSQL VECTOR DDL 컴파일을 확인한다. 실제 OpenAI 호출은 하지 않는다. 별도 테스트 DB의 `AI_TEST_POSTGRES_URL`을 지정하면 `tests/test_pgvector.py`에서 확장·앱 테이블 생성·벡터 저장/조회·색인 롤백·삭제 연쇄 처리를 확인한다. 이 테스트는 테이블을 생성하고 테스트 자료를 쓰므로 개발/실서비스 DB 대신 분리된 테스트 DB를 사용한다. 환경변수가 없으면 이 테스트는 건너뛴다.

```powershell
$env:AI_TEST_POSTGRES_URL = 'postgresql+psycopg://postgres:테스트DB비밀번호@127.0.0.1:55432/find_ai'
python -m pytest -q
Remove-Item Env:AI_TEST_POSTGRES_URL
```

위 URL은 별도로 실행한 테스트 DB 주소로 바꾼다. 실제 사용 환경을 활성화한 후 COLLECT_AND_INDEX 작업이 READY/ready=true/chunkCount>0/indexedAt을 반환하는지 확인하고 저장 자원 조회의 resource_status·chunk_count·embedding_model·embedding_dimensions·indexed_at을 비교한다.

연결·권한·재시작 작업 유실·삭제 이력의 메모리 제약은 기존 [연동 계약](backend-ai-contract.md)과 [API 명세](../api/references.md)를 따른다.
