"""
개발자 B — AI 파이프라인

현장 음성(PCM16) → CLOVA Speech 스트리밍 STT → 텍스트 버퍼 → GPT-4o-mini 의도 분류
→ 오퍼레이터에게 추천(suggestion). 관객에게는 절대 직접 보내지 않는다.
"""
