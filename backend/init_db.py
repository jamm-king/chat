
from app.db.base import Base
from app.db.session import engine

import app.models


def init_db():
    print("1. DB 테이블 생성 시작")

    Base.metadata.create_all(bind=engine)

    print("2. DB 테이블 생성 완료")

    print("생성 대상 테이블:")
    for table_name in Base.metadata.tables.keys():
        print(f"- {table_name}")


if __name__ == "__main__":
    init_db()
