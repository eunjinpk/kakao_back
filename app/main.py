"""
세이프큐 백엔드

공지·템플릿은 SQLite(safeq.db)에 저장된다. 서버를 꺼도 남는다.

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
from app.routers import notices, operator, stream, templates

app = FastAPI(
    title="세이프큐 백엔드",
    version="0.2.0",
    description="공연장 실시간 다국어 비상안내 시스템 · 팀 오롯이닿다",
)

# 개발 중에는 전체 허용. 배포 전에 프론트 도메인만 남긴다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    # 테이블을 만들고, 비어 있으면 data/templates.json 을 넣는다.
    # 이미 들어 있으면 건드리지 않는다 — 화면에서 고친 내용이 날아가면 안 되므로.
    store.load_templates()
    print(f"\n  템플릿 {len(store.list_templates())}개")
    print("  문서  http://localhost:8000/docs\n")


@app.get("/api/health")
def health():
    return {
        "ok": True,
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
        "widgets": list(store.WIDGETS),
        "haptic_intents": list(store.HAPTIC_INTENTS),
    }


app.include_router(notices.router, prefix="/api", tags=["notices"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(stream.router, prefix="/api", tags=["stream"])
app.include_router(operator.router, prefix="/api", tags=["operator"])

# 개발용 마이크 테스트 페이지: http://localhost:8000/static/mic_test.html
_static = Path(__file__).resolve().parents[1] / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=_static), name="static")
