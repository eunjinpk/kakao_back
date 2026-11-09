"""
관객 SSE + 오퍼레이터 WebSocket.

관객: 받기만 한다 (SSE)
오퍼레이터: 오디오를 올리고 추천을 받는다 (WebSocket)
"""
import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
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


@router.websocket("/ws/operator")
async def operator_socket(ws: WebSocket):
    """
    오퍼레이터 PC 연결.

    - 올라오는 것: 마이크 오디오 조각 (더미에서는 무시. 저장하지 않음)
    - 내려가는 것: AI 추천 (개발자 B가 채울 자리. 지금은 가짜 추천)

    더미에서는 15초마다 ETIQUETTE 추천을 한 번씩 보내서
    프론트가 추천 팝업 UI 를 만들 수 있게 한다.
    """
    await ws.accept()
    hub.add_operator(ws)

    async def fake_suggestions():
        samples = ["ETIQUETTE", "DELAY", "INTERMISSION"]
        i = 0
        while True:
            await asyncio.sleep(15)
            intent = samples[i % len(samples)]
            i += 1
            await hub.send_suggestion({
                "event": "suggestion",
                "data": {
                    "intent_type": intent,
                    "stt_text": "(더미) 현장 음성에서 인식된 문장입니다",
                    "templates": store.templates_for_intent(intent),
                },
            })

    task = asyncio.create_task(fake_suggestions())
    try:
        while True:
            # 오디오는 받기만 하고 버린다 (공연 녹음 금지)
            await ws.receive()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        hub.remove_operator(ws)
