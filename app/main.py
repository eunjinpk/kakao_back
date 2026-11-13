"""
세이프큐 백엔드 — W1 더미 서버

DB 없이 메모리로 돌아간다. 프론트가 바로 붙을 수 있게 하는 것이 목적.
W1 후반에 저장소만 SQLAlchemy 로 바꾸면 프론트는 수정 불필요.

실행:
    uvicorn app.main:app --reload --port 8000
문서:
    http://localhost:8000/docs
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import hub, store
from app.routers import notices, operator, stream

app = FastAPI(
    title="세이프큐 백엔드 (더미)",
    version="0.0.1-dummy",
    description="공연장 실시간 다국어 비상안내 시스템 · 팀 오롯이닿다",
)

# W1 은 전체 허용. 배포 전에 프론트 도메인만 남긴다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    store.load_templates()
    print(f"\n  템플릿 {len(store.list_templates())}개 로드됨")
    print("  문서  http://localhost:8000/docs")
    print("  로그인 operator / test1234\n")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": "dummy",
        "templates": len(store.list_templates()),
        "audience_connected": hub.audience_count(),
        "operators_connected": hub.operator_count(),
    }


@app.get("/api/intents")
def intents():
    """프론트·AI 쪽이 목록을 코드에 박지 않게 서버가 알려준다."""
    return {
        "llm_intents": list(store.LLM_INTENTS),
        "template_intents": list(store.TEMPLATE_INTENTS),
        "priority": store.PRIORITY,
    }


app.include_router(notices.router, prefix="/api", tags=["notices"])
app.include_router(stream.router, prefix="/api", tags=["stream"])
app.include_router(operator.router, prefix="/api", tags=["operator"])

# 개발용 마이크 테스트 페이지: http://localhost:8000/static/mic_test.html
_static = Path(__file__).resolve().parents[1] / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=_static), name="static")
