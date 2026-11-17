"""
DB 연결 — SQLite.

safeq.db 파일 하나에 다 들어간다. 서버를 꺼도 공지·템플릿이 남는다.
"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = Path(__file__).resolve().parents[1] / "safeq.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    # SSE·WebSocket 이 서로 다른 스레드에서 같은 연결을 쓸 수 있어서 꺼둔다.
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    """
    WAL: 관객 SSE 가 읽는 동안에도 오퍼레이터가 쓸 수 있게 한다.
    기본 모드면 쓰는 동안 읽기가 막혀서, 공지 송출 때 관객 화면이 잠깐 멈춘다.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI 라우터용. Depends(get_db) 로 받아 쓴다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
