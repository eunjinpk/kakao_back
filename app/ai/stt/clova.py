"""
CLOVA Speech 실시간 스트리밍 (gRPC)

공식 문서: https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-grpc

흐름
  1. 오퍼레이터 WebSocket 하나당 gRPC 양방향 스트림 하나 (요금: 요청 단위 15초 올림 → 청크마다 요청 금지)
  2. 첫 메시지는 CONFIG(JSON), 이후 DATA(PCM 청크)
  3. 응답은 JSON 문자열. responseType 이 transcription 인 것만 텍스트로 쓴다
  4. 오디오가 STT_IDLE_TIMEOUT_SEC 동안 안 오면 스트림을 닫고, 다시 오면 새로 연다

오디오: 헤더 없는 PCM, 16kHz, mono, 16bit (프론트가 그대로 보냄 → 변환 없음)
"""
import asyncio
import json
import logging
import time

import grpc

from app.ai import config
from app.ai.stt import OnTranscript

log = logging.getLogger("safeq.ai.stt.clova")

_CLOSE = object()  # 요청 큐 종료 신호


def build_config() -> dict:
    return {
        "transcription": {"language": config.CLOVA_LANGUAGE},
        # 문장 끊기: 무음(gap) 또는 최대 길이(duration) 기준으로 결과를 자주 받는다
        "semanticEpd": {
            "skipEmptyText": True,
            "usePeriodEpd": True,
            "gapThreshold": config.CLOVA_GAP_THRESHOLD_MS,
            "durationThreshold": config.CLOVA_DURATION_THRESHOLD_MS,
        },
    }


def parse_response(contents: str) -> tuple[str, bool] | None:
    """
    CLOVA 응답 JSON → (text, is_final). 텍스트가 없으면 None.

    CLOVA 스트리밍은 EPD(문장 끝 감지)가 일어날 때 그 구간 결과를 한 번에 준다.
    → 받은 결과는 모두 확정(is_final=True)으로 본다.
    """
    try:
        data = json.loads(contents)
    except (json.JSONDecodeError, TypeError):
        return None
    if data.get("responseType") not in ("transcription", ["transcription"]):
        # config 응답, recognize 상태 응답 등
        if data.get("recognize", {}).get("status") not in (None, "Success", "success"):
            log.warning("CLOVA 상태 응답: %s", data.get("recognize"))
        return None
    text = (data.get("transcription") or {}).get("text", "").strip()
    if not text:
        return None
    return text, True


class ClovaStreamSession:
    provider = "clova"

    def __init__(self, on_transcript: OnTranscript, secret_key: str | None = None,
                 host: str | None = None, idle_timeout: float | None = None,
                 secure: bool = True):
        self.on_transcript = on_transcript
        self.secret_key = secret_key or config.CLOVA_SECRET_KEY
        self.host = host or config.CLOVA_HOST
        self.idle_timeout = idle_timeout or config.STT_IDLE_TIMEOUT_SEC
        self.secure = secure  # 테스트용 로컬 가짜 서버에서만 False

        self._channel: grpc.aio.Channel | None = None
        self._queue: asyncio.Queue | None = None
        self._reader: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._last_audio = 0.0
        self._seq = 0
        self._lock = asyncio.Lock()

    # ── 공개 메서드 ──────────────────────────────────────────────────
    async def start(self) -> None:
        if not self.secret_key:
            raise RuntimeError("CLOVA_SECRET_KEY 가 비어 있습니다 (.env 확인)")
        # 실제 연결은 첫 오디오가 들어올 때 연다 (유휴 연결 방지)

    async def feed(self, pcm: bytes) -> None:
        if not pcm:
            return
        async with self._lock:
            err = self.stream_error
            if err is not None:  # 직전 스트림이 오류로 끊김 → 정리 후 알림 (다음 오디오에서 재연결)
                await self._shutdown()
                raise RuntimeError(f"CLOVA 스트림 오류: {err}")
            if self._queue is None:
                await self._open()
        self._last_audio = time.monotonic()
        self._seq += 1
        await self._queue.put(pcm)

    async def close(self) -> None:
        async with self._lock:
            await self._shutdown()

    # ── 내부 ────────────────────────────────────────────────────────
    async def _open(self) -> None:
        from app.ai.stt.proto import nest_pb2, nest_pb2_grpc

        self._pb2 = nest_pb2
        if self.secure:
            self._channel = grpc.aio.secure_channel(self.host, grpc.ssl_channel_credentials())
        else:
            self._channel = grpc.aio.insecure_channel(self.host)
        stub = nest_pb2_grpc.NestServiceStub(self._channel)
        self._queue = asyncio.Queue()
        self._seq = 0
        # Python 은 메타데이터 키가 소문자여야 한다 (공식 문서)
        call = stub.recognize(self._requests(), metadata=(("authorization", f"Bearer {self.secret_key}"),))
        self._reader = asyncio.create_task(self._read(call))
        self._last_audio = time.monotonic()
        self._watchdog = asyncio.create_task(self._idle_watch())
        log.info("CLOVA 스트림 열림")

    async def _requests(self):
        pb2 = self._pb2
        yield pb2.NestRequest(
            type=pb2.RequestType.CONFIG,
            config=pb2.NestConfig(config=json.dumps(build_config())),
        )
        queue = self._queue
        while True:
            item = await queue.get()
            if item is _CLOSE:
                # 마지막 신호: epFlag=true 로 남은 결과를 즉시 받는다
                yield pb2.NestRequest(
                    type=pb2.RequestType.DATA,
                    data=pb2.NestData(chunk=b"", extra_contents=json.dumps({"seqId": self._seq, "epFlag": True})),
                )
                return
            yield pb2.NestRequest(
                type=pb2.RequestType.DATA,
                data=pb2.NestData(chunk=item, extra_contents=json.dumps({"seqId": 0, "epFlag": False})),
            )

    async def _read(self, call) -> None:
        try:
            async for resp in call:
                parsed = parse_response(resp.contents)
                if parsed:
                    await self.on_transcript(*parsed)
        except grpc.aio.AioRpcError as e:
            log.error("CLOVA 스트림 오류: %s %s", e.code(), e.details())
            raise
        except asyncio.CancelledError:
            pass

    async def _idle_watch(self) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                if time.monotonic() - self._last_audio > self.idle_timeout:
                    log.info("오디오 %ss 없음 → CLOVA 스트림 닫음", self.idle_timeout)
                    async with self._lock:
                        await self._shutdown(from_watchdog=True)
                    return
        except asyncio.CancelledError:
            pass

    async def _shutdown(self, from_watchdog: bool = False) -> None:
        if self._queue is None:
            return
        await self._queue.put(_CLOSE)
        if self._reader:
            try:
                await asyncio.wait_for(self._reader, timeout=5)
            except (asyncio.TimeoutError, Exception):
                self._reader.cancel()
        if self._watchdog and not from_watchdog:
            self._watchdog.cancel()
        if self._channel:
            await self._channel.close()
        self._channel = self._queue = self._reader = self._watchdog = None
        log.info("CLOVA 스트림 닫힘")

    @property
    def stream_error(self) -> BaseException | None:
        """읽기 태스크가 오류로 끝났으면 그 예외 (파이프라인이 error 이벤트로 알림)."""
        if self._reader and self._reader.done() and not self._reader.cancelled():
            return self._reader.exception()
        return None
