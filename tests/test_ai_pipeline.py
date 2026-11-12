"""
개발자 B — AI 파이프라인 테스트. 외부 API 키 없이 돈다.

    pytest -q tests/test_ai_pipeline.py
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import store
from app.ai import config, intents
from app.ai.buffer import TextBuffer
from app.ai.classifier import KeywordClassifier, OpenAIClassifier, build_system_prompt, parse_intent
from app.ai.pipeline import OperatorPipeline
from app.ai.stt.clova import build_config, parse_response
from app.ai.stt.mock import MockSTTSession


# ── intent 목록이 A 쪽 store.py 와 일치하는지 ─────────────────────────
def test_intents_match_store():
    assert tuple(store.LLM_INTENTS) == intents.LLM_INTENTS
    assert tuple(store.TEMPLATE_INTENTS) == intents.TEMPLATE_INTENTS
    assert list(store.PRIORITY) == intents.PRIORITY
    assert set(intents.SUGGESTABLE) == {"FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE"}


def test_every_suggestable_intent_has_template():
    store.load_templates()
    for i in intents.SUGGESTABLE:
        assert store.templates_for_intent(i), f"{i} 템플릿 없음"


# ── 버퍼 ────────────────────────────────────────────────────────────
def test_buffer_keeps_only_window():
    now = [0.0]
    b = TextBuffer(window_sec=10, clock=lambda: now[0])
    b.add("화재가 발생했")
    now[0] = 5
    b.add("비상구로 대피")
    assert b.text() == "화재가 발생했 비상구로 대피"
    now[0] = 12  # 첫 문장은 10초 지남
    assert b.text() == "비상구로 대피"
    b.clear()
    assert b.text() == "" and len(b) == 0


# ── 분류기 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ('{"intent": "FIRE"}', "FIRE"),
    ('{"intent": "fire"}', "FIRE"),
    ('결과: {"intent": "PAUSE"} 입니다', "PAUSE"),
    ('{"intent": "INFO"}', "NONE"),        # INFO 는 LLM 이 뱉으면 안 됨
    ('{"intent": "EARTHQUAKE"}', "NONE"),  # 목록 밖
    ('{"label": "FIRE"}', "NONE"),
    ("FIRE", "NONE"),
    ("", "NONE"),
    (None, "NONE"),
])
def test_parse_intent(raw, expected):
    assert parse_intent(raw) == expected


def test_prompt_has_rules():
    p = build_system_prompt()
    assert "확실하지 않으면 NONE" in p
    assert "FIRE > POWER_OUT > PAUSE > DELAY > INTERMISSION > ETIQUETTE" in p
    for k in intents.LLM_INTENTS:
        assert k in p


class _FakeCompletions:
    def __init__(self, content=None, exc=None):
        self.content, self.exc, self.kwargs = content, exc, None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _fake_client(**kw):
    comp = _FakeCompletions(**kw)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


def test_openai_classifier_request_and_parse():
    client, comp = _fake_client(content='{"intent": "INTERMISSION"}')
    clf = OpenAIClassifier(client=client, model="gpt-4o-mini")
    assert asyncio.run(clf.classify("15분간 인터미션")) == "INTERMISSION"
    assert comp.kwargs["temperature"] == 0
    assert comp.kwargs["response_format"] == {"type": "json_object"}
    assert comp.kwargs["model"] == "gpt-4o-mini"


def test_openai_classifier_failure_is_none():
    client, _ = _fake_client(exc=TimeoutError("slow"))
    assert asyncio.run(OpenAIClassifier(client=client).classify("화재")) == "NONE"


def test_keyword_classifier_priority():
    clf = KeywordClassifier()
    assert asyncio.run(clf.classify("정전으로 공연을 잠시 중단합니다")) == "POWER_OUT"
    assert asyncio.run(clf.classify("안녕하세요")) == "NONE"


# ── CLOVA 응답 파싱 ─────────────────────────────────────────────────
def test_clova_config_and_parse():
    cfg = build_config()
    assert cfg["transcription"]["language"] == "ko"
    assert cfg["semanticEpd"]["gapThreshold"] > 0
    ok = json.dumps({"responseType": ["transcription"], "transcription": {"text": "화재가 발생했습니다"}})
    assert parse_response(ok) == ("화재가 발생했습니다", True)
    assert parse_response(json.dumps({"responseType": "transcription", "transcription": {"text": "  "}})) is None
    assert parse_response(json.dumps({"responseType": ["config"], "config": {"status": "Success"}})) is None
    assert parse_response("not json") is None


# ── 파이프라인 ──────────────────────────────────────────────────────
class _ScriptedClassifier:
    def __init__(self, mapping):
        self.mapping, self.calls = mapping, []

    async def classify(self, text):
        self.calls.append(text)
        for k, v in self.mapping.items():
            if k in text:
                return v
        return "NONE"


def _make_pipeline(lines, mapping, now):
    sent = []

    async def send(msg):
        sent.append(msg)

    stt = MockSTTSession(on_transcript=None, every_sec=1, lines=lines)
    clf = _ScriptedClassifier(mapping)
    p = OperatorPipeline(send=send, session_id="t", stt=stt, classifier=clf,
                         template_lookup=lambda i: [{"template_code": f"{i}_X", "intent_type": i}],
                         clock=lambda: now[0])
    return p, sent, clf


def test_pipeline_transcript_then_suggestion():
    async def go():
        now = [0.0]
        p, sent, _ = _make_pipeline(["화재가 발생했습니다"], {"화재": "FIRE"}, now)
        await p.start()
        await p.feed_audio(b"\x00" * config.BYTES_PER_SEC)  # 1초 → 문장 1개
        await p.drain()
        await p.close()
        return sent

    sent = asyncio.run(go())
    assert [m["type"] for m in sent] == ["transcript", "suggestion"]
    assert sent[0] == {**sent[0], "text": "화재가 발생했습니다", "is_final": True}
    s = sent[1]
    assert s["intent_type"] == "FIRE" and s["templates"][0]["template_code"] == "FIRE_X"
    assert "화재" in s["stt_text"]


def test_pipeline_none_no_suggestion_and_cooldown():
    async def go():
        now = [0.0]
        p, sent, _ = _make_pipeline(["불이야 도망쳐", "촬영 금지", "촬영 금지", "촬영 금지"],
                                    {"촬영": "ETIQUETTE"}, now)
        await p.start()
        for t in (0, 1, 2, 40):  # 1초 오디오마다 문장 하나
            now[0] = t
            await p.feed_audio(b"\x00" * config.BYTES_PER_SEC)
            await p.drain()
        await p.close()
        return sent

    sent = asyncio.run(go())
    sugg = [m for m in sent if m["type"] == "suggestion"]
    # "불이야 도망쳐"(NONE) → 추천 없음 / 촬영 금지 t=1 추천, t=2 쿨다운으로 생략, t=40 다시 추천
    assert len([m for m in sent if m["type"] == "transcript"]) == 4
    assert len(sugg) == 2 and all(m["intent_type"] == "ETIQUETTE" for m in sugg)


def test_pipeline_buffer_joins_fragments():
    async def go():
        now = [0.0]
        p, sent, clf = _make_pipeline(["화재가 발생했", "비상구로 대피"], {"화재가 발생했 비상구로": "FIRE"}, now)
        await p.start()
        await p.feed_audio(b"\x00" * config.BYTES_PER_SEC)
        await p.drain()
        now[0] = 3
        await p.feed_audio(b"\x00" * config.BYTES_PER_SEC)
        await p.drain()
        await p.close()
        return sent, clf

    sent, clf = asyncio.run(go())
    assert clf.calls[-1] == "화재가 발생했 비상구로 대피"
    assert any(m["type"] == "suggestion" for m in sent)
