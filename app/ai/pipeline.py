"""
오퍼레이터 세션 하나의 AI 파이프라인.

  PCM 오디오 ─▶ STT ─▶ transcript 이벤트 (오퍼레이터 화면 실시간 자막)
                   └▶ (확정 문장) 텍스트 버퍼(최근 N초) ─▶ LLM 분류
                        └▶ intent 가 추천 대상이면 suggestion 이벤트 (해당 intent 템플릿 전부)

관객에게는 아무것도 보내지 않는다. 송출은 오퍼레이터가 템플릿을 골라
POST /api/notices 를 호출할 때만 일어난다 (개발자 A 영역).
"""
import asyncio
import logging
import time
import wave
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.ai import config
from app.ai.buffer import TextBuffer
from app.ai.classifier import Classifier, make_classifier
from app.ai.intents import SUGGESTABLE
from app.ai.stt import STTSession, make_stt_session

log = logging.getLogger("safeq.ai.pipeline")

Send = Callable[[dict], Awaitable[None]]
TemplateLookup = Callable[[str], list[dict]]


def _default_template_lookup(intent: str) -> list[dict]:
    from app import store  # 개발자 A 의 저장소 (DB 로 바뀌어도 함수 이름은 유지 합의)

    return store.templates_for_intent(intent)


class OperatorPipeline:
    def __init__(
        self,
        send: Send,
        session_id: str,
        stt: STTSession | None = None,
        classifier: Classifier | None = None,
        template_lookup: TemplateLookup | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.send = send
        self.session_id = session_id
        self.stt = stt or make_stt_session(self._on_transcript)
        if stt is not None:
            stt.on_transcript = self._on_transcript  # 주입된 STT 도 콜백 연결
        self.classifier = classifier or make_classifier()
        self.template_lookup = template_lookup or _default_template_lookup
        self.buffer = TextBuffer(config.BUFFER_WINDOW_SEC, clock=clock)
        self._clock = clock
        self._last_suggested: dict[str, float] = {}
        self._classify_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._wav: wave.Wave_write | None = None

    # ── 생명주기 ────────────────────────────────────────────────────
    async def start(self) -> None:
        if config.DEBUG_SAVE_AUDIO:
            path = Path("tmp/recordings") / f"{self.session_id}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._wav = wave.open(str(path), "wb")
            self._wav.setnchannels(config.CHANNELS)
            self._wav.setsampwidth(config.BYTES_PER_SAMPLE)
            self._wav.setframerate(config.SAMPLE_RATE)
            log.warning("DEBUG_SAVE_AUDIO=on → %s 에 저장 중 (공연 중에는 끄세요)", path)
        await self.stt.start()

    async def feed_audio(self, pcm: bytes) -> None:
        if self._wav:
            self._wav.writeframes(pcm)
        await self.stt.feed(pcm)

    async def close(self) -> None:
        try:
            await self.stt.close()
        finally:
            for t in list(self._tasks):
                t.cancel()
            if self._wav:
                self._wav.close()
                self._wav = None

    # ── STT 결과 처리 ───────────────────────────────────────────────
    async def _on_transcript(self, text: str, is_final: bool) -> None:
        await self.send({"type": "transcript", "text": text, "is_final": is_final, "ts": _now_iso()})
        if not is_final:
            return
        self.buffer.add(text)
        # 분류는 오래 걸릴 수 있으니 STT 수신을 막지 않도록 태스크로 돌린다
        task = asyncio.create_task(self._classify_and_suggest())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _classify_and_suggest(self) -> dict | None:
        async with self._classify_lock:  # 순서 보장: 앞 문장 분류가 끝난 뒤 다음 분류
            window = self.buffer.text()
            if not window:
                return None
            intent = await self.classifier.classify(window)
            log.info("분류: %s ← %r", intent, window)
            if intent not in SUGGESTABLE:
                return None
            now = self._clock()
            last = self._last_suggested.get(intent)
            if last is not None and now - last < config.SUGGEST_COOLDOWN_SEC:
                return None  # 같은 상황 추천 반복 방지
            templates = self.template_lookup(intent)
            if not templates:
                log.warning("intent %s 에 템플릿이 없습니다 (templates.json 확인)", intent)
                return None
            self._last_suggested[intent] = now
            payload: dict[str, Any] = {
                "type": "suggestion",
                "intent_type": intent,
                "stt_text": window,
                "templates": templates,
                "ts": _now_iso(),
            }
            self.buffer.clear()  # 같은 문장으로 다시 추천하지 않도록
            await self.send(payload)
            return payload

    async def drain(self) -> None:
        """테스트용: 진행 중인 분류가 모두 끝날 때까지 기다린다."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
