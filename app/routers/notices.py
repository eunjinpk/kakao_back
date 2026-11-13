"""
공지 — 송출 / 정정 / 종료 / 조회.

생성 경로가 템플릿이든 자유 입력이든 AI 추천을 승인한 것이든,
만들어지는 레코드와 그 뒤 흐름은 완전히 같다.

11/10 회의 결정으로 로그인은 없다. 오퍼레이터 API 도 인증 없이 열려 있다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import hub, store

router = APIRouter()


class NoticeCreate(BaseModel):
    intent_type: str
    template_code: str | None = None
    pictogram_code: str | None = None
    text_ko: str = ""
    text_zh: str = ""
    text_en: str = ""
    direction: str | None = None      # LEFT | RIGHT | FRONT | REAR
    duration_min: int | None = None   # 타이머가 필요한 공지


class NoticePatch(BaseModel):
    text_ko: str | None = None
    text_zh: str | None = None
    text_en: str | None = None
    direction: str | None = None
    pictogram_code: str | None = None
    duration_min: int | None = None


def _publish(action: str, notice: dict, operator_id: int | None):
    event = store.append_event(action, notice, operator_id)
    hub.broadcast(event["event_id"], store.to_sse_payload(event))
    return event


@router.get("/templates")
def get_templates():
    """오퍼레이터 버튼용 템플릿 목록. intent 별로 묶어서도 함께 준다."""
    items = store.list_templates()
    by_intent: dict[str, list] = {}
    for t in items:
        by_intent.setdefault(t["intent_type"], []).append(t)
    return {"templates": items, "by_intent": by_intent}


@router.post("/notices", status_code=201)
def create_notice(body: NoticeCreate):
    if body.intent_type not in store.TEMPLATE_INTENTS:
        raise HTTPException(400, f"invalid_intent_type:{body.intent_type}")

    payload = body.model_dump()

    # 템플릿을 골랐으면 비어 있는 칸을 템플릿 값으로 채운다
    if body.template_code:
        tpl = store.get_template(body.template_code)
        if not tpl:
            raise HTTPException(400, f"unknown_template:{body.template_code}")
        for key in ("pictogram_code", "text_ko", "text_zh", "text_en"):
            if not payload.get(key):
                payload[key] = tpl.get(key)
        if tpl.get("needs_direction") and not payload.get("direction"):
            raise HTTPException(400, "direction_required")
        if tpl.get("needs_duration") and not payload.get("duration_min"):
            raise HTTPException(400, "duration_required")

    if not payload.get("text_ko"):
        raise HTTPException(400, "text_ko_required")

    notice = store.create_notice(payload, None)
    event = _publish("CREATED", notice, None)
    return {"notice": notice, "event_id": event["event_id"]}


@router.patch("/notices/{notice_id}")
def correct_notice(notice_id: int, body: NoticePatch):
    notice = store.get_notice(notice_id)
    if not notice:
        raise HTTPException(404, "notice_not_found")
    if notice["status"] != "ACTIVE":
        raise HTTPException(409, f"cannot_correct_from:{notice['status']}")

    store.correct_notice(notice, body.model_dump(exclude_none=True))
    event = _publish("CORRECTED", notice, None)
    return {"notice": notice, "event_id": event["event_id"]}


@router.post("/notices/{notice_id}/end")
def end_notice(notice_id: int):
    notice = store.get_notice(notice_id)
    if not notice:
        raise HTTPException(404, "notice_not_found")
    if notice["status"] != "ACTIVE":
        raise HTTPException(409, f"cannot_end_from:{notice['status']}")

    store.end_notice(notice)
    event = _publish("ENDED", notice, None)
    return {"notice": notice, "event_id": event["event_id"]}


@router.get("/notices/active")
def list_active():
    """
    인증 없음. 관객이 늦게 접속했거나 네트워크가 끊겼다 붙었을 때
    현재 화면을 맞추는 용도.
    """
    return {
        "notices": [
            {
                "notice_id": n["notice_id"],
                "intent_type": n["intent_type"],
                "pictogram_code": n["pictogram_code"],
                "text_ko": n["text_ko"],
                "text_zh": n["text_zh"],
                "text_en": n["text_en"],
                "trigger_haptic": n["trigger_haptic"],
                "direction": n["direction"],
                "expires_at": n["expires_at"],
                "revision": n["revision"],
            }
            for n in store.active_notices()
        ]
    }
