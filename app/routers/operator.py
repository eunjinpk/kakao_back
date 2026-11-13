"""
오퍼레이터 WebSocket — 개발자 B 담당.

    ws(s)://<host>/api/ws/operator

인증 없음 (11/10 회의: 로그인 제외).

클라이언트 → 서버
  - (binary)            16kHz mono PCM16 오디오 (헤더 없음, little-endian)
  - {"type": "ping"}

서버 → 클라이언트
  - {"type": "connected", "session_id", "stt_provider", "audio": {...}}
  - {"type": "transcript", "text", "is_final", "ts"}
  - {"type": "suggestion", "intent_type", "stt_text", "templates": [...], "ts"}
  - {"type": "error", "code", "message"}
  - {"type": "pong"}

자세한 명세: docs/WS_OPERATOR.md
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import hub
from app.ai import config
from app.ai.pipeline import OperatorPipeline

log = logging.getLogger("safeq.operator_ws")
router = APIRouter()


@router.websocket("/ws/operator")
async def operator_socket(ws: WebSocket):
    await ws.accept()

    session_id = uuid.uuid4().hex[:12]
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        async with send_lock:  # 여러 태스크(STT, 분류)가 동시에 보내도 메시지가 섞이지 않게
            await ws.send_json(msg)

    pipeline = OperatorPipeline(send=send, session_id=session_id)
    hub.add_operator(ws)
    try:
        try:
            await pipeline.start()
        except Exception as e:
            log.exception("파이프라인 시작 실패")
            await send({"type": "error", "code": "STT_UNAVAILABLE", "message": str(e)})

        await send({
            "type": "connected",
            "session_id": session_id,
            "stt_provider": pipeline.stt.provider,
            "audio": {"format": "pcm_s16le", "sample_rate": config.SAMPLE_RATE, "channels": config.CHANNELS},
        })

        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None:
                if len(data) % 2:  # PCM16 은 2바이트 단위
                    await send({"type": "error", "code": "BAD_AUDIO", "message": "PCM16 프레임 길이가 홀수입니다"})
                    continue
                try:
                    await pipeline.feed_audio(data)
                except Exception as e:
                    log.warning("STT 처리 오류: %s", e)
                    await send({"type": "error", "code": "STT_ERROR", "message": str(e)})
                continue
            await _handle_text(msg.get("text"), send)
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_operator(ws)
        await pipeline.close()


async def _handle_text(text: str | None, send) -> None:
    try:
        body = json.loads(text or "")
    except json.JSONDecodeError:
        await send({"type": "error", "code": "BAD_JSON", "message": "JSON 텍스트만 받습니다"})
        return
    kind = body.get("type") if isinstance(body, dict) else None
    if kind == "ping":
        await send({"type": "pong"})
    else:
        await send({"type": "error", "code": "UNKNOWN_TYPE", "message": f"알 수 없는 type: {kind}"})
