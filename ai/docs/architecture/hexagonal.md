# AI 코드 구조

수집·색인·삭제 유스케이스는 외부 기술을 포트로 호출한다. FastAPI·SQLAlchemy·Notion API·LangChain 구현은 어댑터에 둔다. 기존 HTTP 계약·DB 테이블·자료 ID는 유지한다.

```text
app/
├── domain/                   # 자체 문서·색인 명세, 상태·오류, 벡터 검증
├── application/
│   ├── dto.py                # 작업 입력·결과 자료형
│   ├── ports/                # 문서 소스·저장소·청킹·임베딩·실행 인터페이스
│   └── use_cases/            # 수집·색인·삭제 조율, 배치·공개 정책
├── adapters/
│   ├── inbound/http/         # FastAPI 라우트·HTTP 변환·기존 동기 등록 호환
│   └── outbound/
│       ├── notion/           # OAuth·토큰 복호화·공식 API·로더·참조 파싱
│       ├── persistence/      # SQLAlchemy 모델·자료 저장·색인 트랜잭션
│       ├── langchain/        # RecursiveCharacterTextSplitter·OpenAIEmbeddings
│       └── runtime/          # asyncio 작업·스레드 실행·실행 타임아웃
├── bootstrap.py              # 설정·구현체 조립·클라이언트 수명 관리
└── main.py                   # 기존 app.main:app 진입점
```

## 의존성 방향

domain은 application·adapters에 의존하지 않는다. application은 domain과 자신이 정의한 포트에 의존한다. 구체적인 어댑터·환경 설정·HTTP·ORM·LangChain을 import하지 않는다. 어댑터가 안쪽 포트를 구현하며 bootstrap이 연결한다. 작업 DTO는 Pydantic으로 검증하되 FastAPI에 의존하지 않는다.

애플리케이션은 `TextDocument`를 사용한다. Notion 로더 내부의 LangChain Document는 `NotionDocumentSource`가 변환하며, 청킹 어댑터도 경계에서만 LangChain Document를 사용한다. SDK·ORM 예외는 어댑터가 `SourceError`·`StorageError`·`EmbeddingError`로 변환하고 내부 응답·키·SQL을 전달하지 않는다.

| 포트 | 구현 | 책임 |
| --- | --- | --- |
| DocumentSource | NotionDocumentSource | 연결의 토큰으로 지정한 페이지 수집 |
| ResourceStore | SqlAlchemyResourceStore | 소유권·참조 확인, 스냅샷 저장, 색인 공개, 조회·삭제 |
| TextChunker | LangChainTextChunker | 텍스트 경계·오프셋을 보존한 분할 |
| EmbeddingClient | OpenAIEmbeddingClient | LangChain OpenAI 임베딩 호출 |
| JobExecutor | AsyncioJobExecutor | 작업 예약·종료·스레드 호출·호출 기한 |

IngestionManager는 접수·작업 상태·기한·삭제 제외를 조율하고 DocumentIndexer는 본문 완전성·빈 텍스트·배치·벡터 검증을 담당한다. 메모리 작업 저장과 공개 잠금은 기존 단일 프로세스 구현을 유지한다. 이 리팩토링으로 영속 큐나 재시작 복구를 추가하지 않는다.

## 트랜잭션·호환 동작

`ResourceStore.publish_index`는 모든 청크·벡터와 완료 레코드를 한 트랜잭션으로 저장한다. 성공 반환 후에만 READY로 바꾼다. 수집 스냅샷은 별도 저장하므로 색인 실패 후 재사용할 수 있다.

삭제와 스냅샷·색인 공개는 같은 유스케이스 잠금을 사용한다. 외부 호출을 기다리는 동안 잠금을 잡지 않으며, 늦게 끝난 호출은 삭제·기한을 다시 확인한 뒤 저장을 중단한다. 기존 동기 등록은 inbound/http/registration.py의 호환 경로에서 동일한 잠금을 사용한다. 삭제 실패 시 메모리 제외 표시는 유지한다.

OAuth 쿠키·콜백 처리와 페이지 검색·미리보기는 기존 HTTP 어댑터에서 유지하고, 토큰 교환·암호화와 Notion 호출은 outbound/notion에 둔다. deprecated 동기 등록도 HTTP 호환 경로로 유지한다. 검색·답변 유스케이스는 application/use_cases/retrieval.py·answers.py와 RetrievalStore·AnswerGenerator 포트를 사용한다. PostgreSQL 검색과 LangChain ChatOpenAI는 외부 어댑터가 구현한다. [실행 안내](retrieval-and-answers.md)를 따른다.

## 검증

`tests/test_hexagonal_architecture.py`는 코어 의존성 방향을 검사하고, 외부 어댑터 없이 수집·색인·스냅샷 재사용·오류·삭제를 검증한다. 기존 HTTP·저장·취소 경합 회귀 테스트를 유지한다. `AI_TEST_POSTGRES_URL`을 지정하면 실제 pgvector 통합 테스트도 실행된다. 실제 OpenAI 호출은 자동 테스트에서 수행하지 않는다.
