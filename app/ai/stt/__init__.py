"""
STT (음성 → 텍스트)

업체를 바꿔 끼울 수 있게 세션 인터페이스 하나로 감싼다.
    session = make_stt_session(on_transcript)
    await session.start()
    await session.feed(pcm_bytes)   # 16kHz mono PCM16
    await session.close()

on_transcript(text: str, is_final: bool) 는 결과가 나올 때마다 호출된다.
"""
from typing import Awaitable, Callable, Protocol

from app.ai import config

OnTranscript = Callable[[str, bool], Awaitable[None]]


class STTSession(Protocol):
    provider: str

    async def start(self) -> None: ...
    async def feed(self, pcm: bytes) -> None: ...
    async def close(self) -> None: ...


def make_stt_session(on_transcript: OnTranscript, provider: str | None = None) -> STTSession:
    provider = (provider or config.STT_PROVIDER).lower()
    if provider == "clova":
        from app.ai.stt.clova import ClovaStreamSession

        return ClovaStreamSession(on_transcript)
    from app.ai.stt.mock import MockSTTSession

    return MockSTTSession(on_transcript)
