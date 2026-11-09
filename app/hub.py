"""
관객 SSE 구독자 관리 + 오퍼레이터 WebSocket 연결 관리.
"""
import asyncio
from typing import Any

# 관객 SSE 구독자 — 각자 자기 큐를 하나씩 들고 있다
_audience: set[asyncio.Queue] = set()

# 오퍼레이터 WebSocket 연결 (추천을 보낼 대상)
_operators: set[Any] = set()


# ── 관객 SSE ────────────────────────────────────────────────────────
def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _audience.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _audience.discard(q)


def broadcast(event_id: int, data: dict) -> None:
    """모든 관객 기기에 같은 이벤트를 밀어넣는다."""
    for q in list(_audience):
        q.put_nowait({"id": str(event_id), "event": "notice_update", "data": data})


def audience_count() -> int:
    return len(_audience)


# ── 오퍼레이터 WebSocket ────────────────────────────────────────────
def add_operator(ws) -> None:
    _operators.add(ws)


def remove_operator(ws) -> None:
    _operators.discard(ws)


async def send_suggestion(payload: dict) -> None:
    """AI 추천을 오퍼레이터 화면에만 보낸다. 관객에게는 가지 않는다."""
    for ws in list(_operators):
        try:
            await ws.send_json(payload)
        except Exception:
            _operators.discard(ws)


def operator_count() -> int:
    return len(_operators)
