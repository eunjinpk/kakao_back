"""
CLOVA 스트리밍 단독 테스트 — 녹음 파일을 실시간처럼 흘려보내고 인식 결과를 출력한다.
서버/프론트 없이 CLOVA 연결(키, proto, 인증)만 먼저 확인할 때 쓴다.

준비: 16kHz mono 16bit WAV 파일
    ffmpeg -i 원본.m4a -ar 16000 -ac 1 -sample_fmt s16 test.wav

사용법 (레포 루트, .env 에 CLOVA_SECRET_KEY 설정 후):
    python -m scripts.clova_file_test test.wav
    python -m scripts.clova_file_test test.wav --fast   # 기다리지 않고 바로 전송
"""
import argparse
import asyncio
import time
import wave

from app.ai import config
from app.ai.stt.clova import ClovaStreamSession

FRAME_MS = 100


async def main(path: str, fast: bool) -> None:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == config.SAMPLE_RATE, f"샘플레이트가 {w.getframerate()}Hz 입니다. 16000Hz 로 변환하세요"
        assert w.getnchannels() == 1, "mono 파일이 필요합니다"
        assert w.getsampwidth() == 2, "16bit 파일이 필요합니다"
        pcm = w.readframes(w.getnframes())

    t0 = time.perf_counter()

    async def on_transcript(text: str, is_final: bool) -> None:
        print(f"[{time.perf_counter() - t0:6.2f}s] {'확정' if is_final else '중간'}: {text}")

    session = ClovaStreamSession(on_transcript)
    await session.start()
    step = config.BYTES_PER_SEC * FRAME_MS // 1000
    print(f"전송 시작: {len(pcm) / config.BYTES_PER_SEC:.1f}초 분량")
    for i in range(0, len(pcm), step):
        await session.feed(pcm[i:i + step])
        if not fast:
            await asyncio.sleep(FRAME_MS / 1000)
    print("전송 끝 → 남은 결과 대기")
    await session.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.wav, a.fast))
