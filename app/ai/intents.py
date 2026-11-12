"""
intent 정의 — LLM 프롬프트와 평가 스크립트가 함께 쓴다.

목록 자체는 app/store.py 의 LLM_INTENTS / TEMPLATE_INTENTS 와 같아야 한다.
(어느 한쪽에서 import 하도록 A 와 합의 예정. 지금은 테스트로 일치 여부를 확인한다.)
"""

LLM_INTENTS = ("FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE", "NONE")
TEMPLATE_INTENTS = ("FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE", "INFO")

# 한 발화가 여러 상황에 걸치면 앞쪽(더 긴급한 쪽)으로 분류한다
PRIORITY = ["FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE"]

# AI 추천으로 이어지는 intent = 두 목록의 교집합 (NONE 은 템플릿 없음, INFO 는 LLM 이 안 뱉음)
SUGGESTABLE = tuple(i for i in LLM_INTENTS if i in TEMPLATE_INTENTS)

# 프롬프트에 그대로 들어가는 설명
DEFINITIONS = {
    "FIRE": "화재, 지진 등 관객 대피가 필요한 비상 상황 안내",
    "POWER_OUT": "정전, 음향·조명 등 설비 이상 안내",
    "PAUSE": "공연 도중 공연을 일시 중단한다는 안내",
    "DELAY": "공연 시작 전, 시작이 지연된다는 안내",
    "INTERMISSION": "인터미션(중간 휴식) 시작 또는 종료 안내",
    "ETIQUETTE": "촬영·녹음·취식·휴대폰 사용 금지 등 관람 예절 안내",
    "NONE": "위에 해당하지 않음. 공연 대사, 노래 가사, 관객 잡담, 의미를 알 수 없는 소음, 확실하지 않은 경우",
}
