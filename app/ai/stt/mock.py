"""
개발용 가짜 STT — CLOVA 키 없이 오퍼레이터 화면/파이프라인을 붙여볼 때.

실제로 소리를 알아듣지는 않는다. 오디오가 MOCK_STT_EVERY_SEC 초 분량 들어올 때마다
아래 샘플 문장을 순서대로 하나씩 transcript 로 낸다.
"""
from app.ai import config
from app.ai.stt import OnTranscript

SAMPLE_LINES = [
    "공연 시작 전 안내 말씀드립니다",
    "공연 중 사진 및 영상 촬영은 금지되어 있습니다",
    "잠시 후 15분간 인터미션이 있겠습니다",
    "불이야 모두 도망쳐",  # 공연 대사 → NONE 이어야 함
    "화재가 발생했습니다 가까운 비상구로 대피해 주십시오",
]


class MockSTTSession:
    provider = "mock"

    def __init__(self, on_transcript: OnTranscript, every_sec: float | None = None,
                 lines: list[str] | None = None):
        self.on_transcript = on_transcript
        self.every_bytes = int((every_sec or config.MOCK_STT_EVERY_SEC) * config.BYTES_PER_SEC)
        self.lines = lines or SAMPLE_LINES
        self._received = 0
        self._idx = 0

    async def start(self) -> None:
        pass

    async def feed(self, pcm: bytes) -> None:
        self._received += len(pcm)
        while self._received >= self.every_bytes:
            self._received -= self.every_bytes
            line = self.lines[self._idx % len(self.lines)]
            self._idx += 1
            await self.on_transcript(line, True)

    async def close(self) -> None:
        pass
