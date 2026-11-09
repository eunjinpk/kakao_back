"""
메모리 저장소 — 더미 서버용. DB 없이 돌아간다.

W1 후반에 이 파일의 함수들만 SQLAlchemy 쿼리로 바꿔 끼우면
라우터와 프론트는 전혀 수정하지 않아도 된다.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# 기획서 섹션 4
LLM_INTENTS = ("FIRE", "POWER_OUT", "PAUSE", "DELAY",
               "INTERMISSION", "ETIQUETTE", "NONE")
TEMPLATE_INTENTS = ("FIRE", "POWER_OUT", "PAUSE", "DELAY",
                    "INTERMISSION", "ETIQUETTE", "INFO")
PRIORITY = ["FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE"]

# ── 템플릿 (설정 파일에서 읽음 — 개발자 B 관리) ──────────────────────
_templates: list[dict] = []


def load_templates() -> list[dict]:
    global _templates
    raw = json.loads((DATA_DIR / "templates.json").read_text(encoding="utf-8"))
    _templates = [t for t in raw["templates"]]
    for t in _templates:
        if t["intent_type"] not in TEMPLATE_INTENTS:
            raise ValueError(f"알 수 없는 intent_type: {t['intent_type']}")
    return _templates


def list_templates() -> list[dict]:
    return _templates


def get_template(code: str) -> dict | None:
    return next((t for t in _templates if t["template_code"] == code), None)


def templates_for_intent(intent: str) -> list[dict]:
    return [t for t in _templates if t["intent_type"] == intent]


# ── 공지 ────────────────────────────────────────────────────────────
_notices: dict[int, dict] = {}
_events: list[dict] = []
_notice_seq = 100


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_notice(payload: dict, operator_id: int) -> dict:
    global _notice_seq
    _notice_seq += 1

    expires_at = None
    if payload.get("duration_min"):
        expires_at = (datetime.now(timezone.utc)
                      + timedelta(minutes=int(payload["duration_min"]))).isoformat()

    notice = {
        "notice_id": _notice_seq,
        "status": "ACTIVE",
        "intent_type": payload["intent_type"],
        "template_code": payload.get("template_code"),
        "pictogram_code": payload.get("pictogram_code"),
        "text_ko": payload.get("text_ko", ""),
        "text_zh": payload.get("text_zh", ""),
        "text_en": payload.get("text_en", ""),
        # 아래 3개는 기획서 SSE 예시에 없지만 기능 ③⑥⑦에 필요해서 추가 (README 참고)
        "direction": payload.get("direction"),
        "expires_at": expires_at,
        "revision": 0,
        "trigger_haptic": payload["intent_type"] in ("FIRE", "POWER_OUT"),
        "created_by": operator_id,
        "created_at": now(),
        "updated_at": None,
        "ended_at": None,
    }
    _notices[notice["notice_id"]] = notice
    return notice


def get_notice(notice_id: int) -> dict | None:
    return _notices.get(notice_id)


def active_notices() -> list[dict]:
    return [n for n in _notices.values() if n["status"] == "ACTIVE"]


def correct_notice(notice: dict, payload: dict) -> dict:
    for key in ("text_ko", "text_zh", "text_en", "direction", "pictogram_code"):
        if key in payload and payload[key] is not None:
            notice[key] = payload[key]
    if payload.get("duration_min"):
        notice["expires_at"] = (datetime.now(timezone.utc)
                                + timedelta(minutes=int(payload["duration_min"]))).isoformat()
    notice["revision"] += 1
    notice["updated_at"] = now()
    return notice


def end_notice(notice: dict) -> dict:
    notice["status"] = "ENDED"
    notice["ended_at"] = now()
    return notice


# ── 이벤트 (SSE 재전송 기준) ─────────────────────────────────────────
def append_event(action: str, notice: dict, operator_id: int | None) -> dict:
    """
    이벤트마다 번호를 매긴다. 공지 id 를 SSE id 로 쓰면
    같은 공지의 CREATED 와 ENDED 가 같은 번호가 되어 재접속 복구가 깨진다.
    """
    event = {
        "event_id": len(_events) + 1,
        "action": action,
        "operator_id": operator_id,
        "snapshot": dict(notice),      # 이 시점 공지 전체 (모든 언어 포함)
        "created_at": now(),
    }
    _events.append(event)
    return event


def events_after(last_event_id: int) -> list[dict]:
    return [e for e in _events if e["event_id"] > last_event_id]


def to_sse_payload(event: dict) -> dict[str, Any]:
    """기획서 '관객 SSE 데이터 예시' 형식."""
    n = event["snapshot"]
    return {
        "notice_id": n["notice_id"],
        "action": event["action"],
        "intent_type": n["intent_type"],
        "pictogram_code": n["pictogram_code"],
        "text_ko": n["text_ko"],
        "text_zh": n["text_zh"],
        "text_en": n["text_en"],
        "trigger_haptic": n["trigger_haptic"],
        # 추가 필드 (프론트가 모르면 무시해도 깨지지 않음)
        "direction": n["direction"],
        "expires_at": n["expires_at"],
        "revision": n["revision"],
    }
