"""
AI 파이프라인 설정. 전부 .env 로 바꿀 수 있다 (.env.example 참고).
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv 가 없어도 동작
    pass


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ── STT ──────────────────────────────────────────────────────────────
# clova: CLOVA Speech 실시간 스트리밍 (gRPC)
# mock : 키 없이 개발할 때. 오디오가 일정량 들어오면 샘플 문장을 transcript 로 낸다
STT_PROVIDER = os.getenv("STT_PROVIDER", "mock").strip().lower()

CLOVA_SECRET_KEY = os.getenv("CLOVA_SECRET_KEY", "")
CLOVA_HOST = os.getenv("CLOVA_HOST", "clovaspeech-gw.ncloud.com:50051")
CLOVA_LANGUAGE = os.getenv("CLOVA_LANGUAGE", "ko")
# 문장 끊기 기준 (ms). 짧을수록 transcript 가 자주, 빨리 온다
CLOVA_GAP_THRESHOLD_MS = _int("CLOVA_GAP_THRESHOLD_MS", 600)
CLOVA_DURATION_THRESHOLD_MS = _int("CLOVA_DURATION_THRESHOLD_MS", 6000)

# 오디오가 이 시간(초) 동안 안 들어오면 CLOVA 연결을 닫는다 (권장사항: 유휴 커넥션 정리)
STT_IDLE_TIMEOUT_SEC = _int("STT_IDLE_TIMEOUT_SEC", 30)

# mock STT: 몇 초 분량의 오디오마다 문장 하나를 낼지
MOCK_STT_EVERY_SEC = float(os.getenv("MOCK_STT_EVERY_SEC", "3"))

# ── 오디오 형식 (피드백 #2: 16kHz mono PCM16) ──────────────────────────
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE  # 32,000

# 공연 녹음 금지 원칙: 기본값 False. 로컬 디버깅 때만 켠다 (tmp/recordings/*.wav)
DEBUG_SAVE_AUDIO = _bool("DEBUG_SAVE_AUDIO", False)

# ── LLM ──────────────────────────────────────────────────────────────
# openai: GPT-4o-mini
# mock  : 키 없이 개발할 때. 키워드 규칙으로 분류
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").strip().lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "") or os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "5"))

# ── 버퍼 / 추천 ──────────────────────────────────────────────────────
BUFFER_WINDOW_SEC = _int("BUFFER_WINDOW_SEC", 10)
# 같은 intent 추천을 이 시간(초) 동안 다시 보내지 않는다 (팝업 도배 방지)
SUGGEST_COOLDOWN_SEC = _int("SUGGEST_COOLDOWN_SEC", 30)
