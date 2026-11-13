"""
의도 분류기 — STT 텍스트를 intent 하나로 바꾼다.

- 실제: GPT-4o-mini (JSON 출력, temperature 0)
- 개발용: 키워드 규칙 (키 없이 프론트/파이프라인을 붙여볼 때)

어떤 경우든 결과는 LLM_INTENTS 중 하나다. 이상한 값, 파싱 실패, 타임아웃은 전부 NONE.
→ "확실하지 않으면 NONE" 이 오경보를 막는 마지막 장치.
"""
import json
import logging
import re
from typing import Protocol

from app.ai import config
from app.ai.intents import DEFINITIONS, LLM_INTENTS, PRIORITY

log = logging.getLogger("safeq.ai.classifier")


# ── 프롬프트 v1 ──────────────────────────────────────────────────────
def build_system_prompt() -> str:
    defs = "\n".join(f"- {k}: {v}" for k, v in DEFINITIONS.items())
    order = " > ".join(PRIORITY)
    return f"""너는 공연장 안내 방송 분류기다.
입력은 소음과 잔향이 심한 공연장에서 받은 음성 인식(STT) 결과라서 글자가 틀리거나 문장이 끊겨 있을 수 있다.
입력이 어떤 안내 방송인지 아래 분류 중 정확히 하나를 골라라.

[분류]
{defs}

[규칙]
1. 확실하지 않으면 NONE 을 고른다. 억지로 다른 분류를 고르지 않는다.
2. 안내 방송(스태프가 관객에게 하는 공지) 형태의 발화만 분류한다.
   공연 대사, 노래 가사, 관객끼리의 대화는 내용이 비슷해도 NONE 이다.
   예: 배우가 외치는 "불이야! 도망쳐!" 는 NONE.
3. 한 발화가 여러 분류에 걸치면 우선순위가 높은 쪽을 고른다: {order}
   예: "정전으로 공연을 잠시 중단합니다" 는 POWER_OUT.
4. 글자가 깨져 있어도 안내 의도가 분명하면 분류한다.
   예: "화재가 발생했... 비상구로 대파..." 는 FIRE.

[출력]
JSON 하나만 출력한다. 다른 글자는 쓰지 않는다.
{{"intent": "<분류 이름>"}}"""


def parse_intent(raw: str | None) -> str:
    """LLM 응답 문자열 → intent. 규격에 안 맞으면 전부 NONE."""
    if not raw:
        return "NONE"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # 앞뒤에 잡문이 붙은 경우 첫 번째 {...} 만 다시 시도
        m = re.search(r"\{.*?\}", raw, re.S)
        if not m:
            return "NONE"
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return "NONE"
    if not isinstance(data, dict):
        return "NONE"
    intent = str(data.get("intent", "")).strip().upper()
    return intent if intent in LLM_INTENTS else "NONE"


class Classifier(Protocol):
    async def classify(self, text: str) -> str: ...


# ── GPT-4o-mini ──────────────────────────────────────────────────────
class OpenAIClassifier:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float | None = None, client=None):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key or config.OPENAI_API_KEY)
        self.client = client
        self.model = model or config.LLM_MODEL
        self.timeout = timeout or config.LLM_TIMEOUT_SEC
        self.system_prompt = build_system_prompt()

    async def classify(self, text: str) -> str:
        if not text.strip():
            return "NONE"
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_tokens=20,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": text},
                ],
                timeout=self.timeout,
            )
            raw = resp.choices[0].message.content
        except Exception as e:  # 네트워크, 타임아웃, 요금 한도 등 → 추천 안 함
            log.warning("LLM 호출 실패 → NONE 처리: %s", e)
            return "NONE"
        return parse_intent(raw)


# ── 개발용 키워드 분류기 ─────────────────────────────────────────────
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("FIRE", ("화재", "불이 났", "대피", "비상구", "지진")),
    ("POWER_OUT", ("정전", "전기", "설비", "음향 장비")),
    ("PAUSE", ("중단", "멈추", "중지")),
    ("DELAY", ("지연", "늦어", "시작이 늦")),
    ("INTERMISSION", ("인터미션", "휴식", "쉬는 시간")),
    ("ETIQUETTE", ("촬영", "녹음", "취식", "음식", "휴대폰", "휴대전화")),
]


class KeywordClassifier:
    """LLM 키 없이 파이프라인을 돌려볼 때만 쓴다. 정확도 평가 대상 아님."""

    async def classify(self, text: str) -> str:
        for intent in PRIORITY:  # 우선순위 순서로 검사
            words = dict(_KEYWORDS)[intent]
            if any(w in text for w in words):
                return intent
        return "NONE"


def make_classifier(provider: str | None = None) -> Classifier:
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider == "openai":
        return OpenAIClassifier()
    return KeywordClassifier()
