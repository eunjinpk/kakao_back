"""
오퍼레이터 WebSocket 통합 테스트 (mock STT + 키워드 분류기, 외부 API 없음)

    pytest -q tests/test_operator_ws.py
"""
import pytest
from fastapi.testclient import TestClient

from app.ai import config


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "STT_PROVIDER", "mock")
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(config, "MOCK_STT_EVERY_SEC", 1)
    monkeypatch.setattr(config, "DEBUG_SAVE_AUDIO", False)
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_connects_without_auth(client):
    """11/10 회의: 로그인 제외 → 토큰 없이 바로 연결"""
    with client.websocket_connect("/api/ws/operator") as ws:
        assert ws.receive_json()["type"] == "connected"


def test_connected_ping_pong_and_errors(client):
    with client.websocket_connect("/api/ws/operator") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        assert hello["audio"] == {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1}
        assert hello["stt_provider"] == "mock"

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        ws.send_json({"type": "hello"})
        assert ws.receive_json()["code"] == "UNKNOWN_TYPE"

        ws.send_bytes(b"\x00\x00\x00")  # 홀수 길이
        assert ws.receive_json()["code"] == "BAD_AUDIO"


def test_audio_to_transcript_and_suggestion(client):
    """mock STT 문장 순서: 안내 → 촬영 금지(추천) → 인터미션(추천) → 공연 대사(NONE) → 화재(추천)"""
    with client.websocket_connect("/api/ws/operator") as ws:
        assert ws.receive_json()["type"] == "connected"
        one_sec = b"\x00" * config.BYTES_PER_SEC
        got = []
        for _ in range(5):
            # 100ms 프레임 10개 = 1초 → 문장 1개
            for _ in range(10):
                ws.send_bytes(one_sec[: config.BYTES_PER_SEC // 10])
            got.append(ws.receive_json())  # transcript
            if got[-1]["text"] != "공연 시작 전 안내 말씀드립니다" and "불이야" not in got[-1]["text"]:
                got.append(ws.receive_json())  # suggestion

        types = [m["type"] for m in got]
        assert types.count("transcript") == 5
        sugg = [m for m in got if m["type"] == "suggestion"]
        assert [m["intent_type"] for m in sugg] == ["ETIQUETTE", "INTERMISSION", "FIRE"]
        fire = sugg[-1]
        assert {t["template_code"] for t in fire["templates"]} == {"FIRE_EVAC"}
        etq = sugg[0]
        assert {t["template_code"] for t in etq["templates"]} >= {"ETIQUETTE_PHOTO", "ETIQUETTE_FOOD"}


def test_sse_still_works_after_split(client):
    """A 의 관객 SSE 경로가 그대로 등록돼 있는지 (WebSocket 분리 영향 없음)"""
    schema = client.get("/openapi.json").json()
    assert "/api/stream/notices" in schema["paths"]
    with client.websocket_connect("/api/ws/operator") as ws:
        assert ws.receive_json()["type"] == "connected"
