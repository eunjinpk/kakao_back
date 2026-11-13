"""
관객 SSE. 관객은 받기만 한다.

오퍼레이터 WebSocket 은 app/routers/operator.py (개발자 B).
"""
import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app import hub, store

router = APIRouter()

HEARTBEAT_SEC = 15


@router.get("/stream/notices")
async def stream_notices(request: Request):
    """
    관객 기기 구독. 인증 없음.

    끊겼다 붙으면 브라우저가 Last-Event-ID 헤더를 자동으로 보낸다.
    그 번호 이후 이벤트를 먼저 전부 흘려보낸 뒤 실시간으로 넘어간다.
    """
    last_id = request.headers.get("last-event-id") or request.query_params.get("lastEventId") or 0
    try:
        last_id = int(last_id)
    except (TypeError, ValueError):
        last_id = 0

    queue = hub.subscribe()

    async def gen():
        try:
            # 1) 놓친 것 먼저
            for event in store.events_after(last_id):
                yield {
                    "id": str(event["event_id"]),
                    "event": "notice_update",
                    "data": json.dumps(store.to_sse_payload(event), ensure_ascii=False),
                }
            # 2) 이후 실시간
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SEC)
                    yield {
                        "id": msg["id"],
                        "event": msg["event"],
                        "data": json.dumps(msg["data"], ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
        finally:
            hub.unsubscribe(queue)

    return EventSourceResponse(gen())


# 오퍼레이터 WebSocket 은 app/routers/operator.py 로 이동 (개발자 B 담당)
