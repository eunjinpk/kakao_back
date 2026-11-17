"""
저장소 — DB(SQLite) 를 감싼다.

바깥에서 부르는 아래 함수는 이름도 모양도 그대로 두었다. DB 세션을 받지 않고
안에서 열었다가 바로 닫는다. 그래서 부르는 쪽 코드는 고칠 게 없다.

    load_templates()              main.py 시작할 때
    list_templates()              main.py /api/health
    templates_for_intent(intent)  app/ai/pipeline.py  (개발자 B)
    events_after(last_id)         routers/stream.py
    to_sse_payload(event)         routers/stream.py

라우터에서 쓰는 함수는 Depends(get_db) 로 받은 세션을 첫 인자로 넘긴다.

주의: 공지를 바꾸는 함수는 hub.broadcast() 를 부른다. broadcast 는
asyncio 큐에 넣기 때문에 이벤트 루프 안에서 불려야 한다.
→ 공지를 다루는 라우터는 반드시 async def 로 만든다.
"""
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app import hub
from app.db import SessionLocal
from app.models import (
    EVENT_KINDS, HAPTIC_INTENTS, LLM_INTENTS, NOTICE_STATUS, PRIORITY,
    TEMPLATE_INTENTS, WIDGETS, Notice, NoticeEvent, NoticeTemplate, Pictogram,
    now,
)

__all__ = [
    "LLM_INTENTS", "TEMPLATE_INTENTS", "PRIORITY", "HAPTIC_INTENTS", "WIDGETS",
    "load_templates", "list_templates", "templates_for_intent",
    "events_after", "to_sse_payload",
]

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "templates.json"

# 기본 픽토그램. 디자인팀 SVG 파일명이 확정되면 name 을 맞춘다.
SEED_PICTOGRAMS = [
    ("fire_exit", "비상구", 10),
    ("evacuate", "대피", 20),
    ("wait", "대기", 30),
    ("pause", "일시정지", 40),
    ("clock", "시계", 50),
    ("no_photo", "촬영 금지", 60),
    ("no_phone", "휴대폰 금지", 70),
    ("no_food", "취식 금지", 80),
    ("info", "일반 안내", 90),
]


class StoreError(Exception):
    """라우터가 HTTP 응답으로 바꿔 주는 오류. code 로 구분한다."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# ── ORM → dict ─────────────────────────────────────────────────────────
def _tpl_dict(t: NoticeTemplate) -> dict:
    return {
        "code": t.code,
        "intent_type": t.intent_type,
        "title": t.title,
        "text_ko": t.text_ko,
        "text_en": t.text_en,
        "text_zh": t.text_zh,
        "text_ja": t.text_ja,
        "pictogram": t.pictogram,
        "widget": t.widget,
        "needs_duration": t.needs_duration,
        "default_minutes": t.default_minutes,
        "trigger_haptic": t.trigger_haptic,
        "is_default": t.is_default,
        "is_active": t.is_active,
        "sort_order": t.sort_order,
    }


def _notice_dict(n: Notice) -> dict:
    return {
        "id": n.id,
        "template_code": n.template_code,
        "intent_type": n.intent_type,
        "title": None,
        "text_ko": n.text_ko,
        "text_en": n.text_en,
        "text_zh": n.text_zh,
        "text_ja": n.text_ja,
        "pictogram": n.pictogram,
        "widget": n.widget,
        "minutes": n.minutes,
        "expires_at": n.expires_at.isoformat() + "Z" if n.expires_at else None,
        "direction": n.direction,
        "trigger_haptic": n.trigger_haptic,
        "operator_name": n.operator_name,
        "status": n.status,
        "revision": n.revision,
        "created_at": n.created_at.isoformat() + "Z",
        "ended_at": n.ended_at.isoformat() + "Z" if n.ended_at else None,
    }


def _fill_minutes(text: str, minutes) -> str:
    """'{minutes}분 지연' → '10분 지연'. 언어마다 숫자 위치가 달라서 자리표시자를 쓴다."""
    if minutes is None or not text:
        return text or ""
    return text.replace("{minutes}", str(minutes))


# ── 시딩 ────────────────────────────────────────────────────────────────
def _seed(db: Session) -> None:
    """비어 있을 때만 넣는다. 화면에서 고친 내용을 덮어쓰지 않기 위해서다."""
    if db.query(Pictogram).count() == 0:
        for name, label, order in SEED_PICTOGRAMS:
            db.add(Pictogram(name=name, label_ko=label,
                             file_name=f"{name}.svg", sort_order=order))
        db.commit()

    if db.query(NoticeTemplate).count() > 0:
        return
    if not SEED_FILE.is_file():
        print(f"  [경고] {SEED_FILE} 가 없어 템플릿을 넣지 못했습니다")
        return

    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    for item in raw.get("templates", []):
        db.add(NoticeTemplate(
            code=item["code"],
            intent_type=item["intent_type"],
            title=item["title"],
            text_ko=item.get("text_ko", ""),
            text_en=item.get("text_en", ""),
            text_zh=item.get("text_zh", ""),
            text_ja=item.get("text_ja", ""),
            pictogram=item.get("pictogram"),
            widget=item.get("widget", "none"),
            needs_duration=bool(item.get("needs_duration", False)),
            default_minutes=item.get("default_minutes"),
            trigger_haptic=bool(item.get("trigger_haptic", False)),
            is_default=bool(item.get("is_default", False)),
            sort_order=int(item.get("sort_order", 100)),
        ))
    db.commit()


def load_templates() -> None:
    """main.py 시작할 때. 테이블을 만들고, 비어 있으면 초기 데이터를 넣는다."""
    from app.db import Base, engine
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _seed(db)


# ── 템플릿 조회 (세션 없이 부르는 쪽) ───────────────────────────────────
def list_templates(include_inactive: bool = False) -> list[dict]:
    with SessionLocal() as db:
        return list_templates_db(db, include_inactive)


def templates_for_intent(intent: str) -> list[dict]:
    """
    개발자 B 의 추천 파이프라인이 부른다. 동기 함수, 템플릿 dict 목록.
    sort_order 순으로 돌려주므로 앞에서부터 잘라 쓰면 된다.
    """
    with SessionLocal() as db:
        rows = (
            db.query(NoticeTemplate)
            .filter(NoticeTemplate.intent_type == intent,
                    NoticeTemplate.is_active.is_(True))
            .order_by(NoticeTemplate.sort_order, NoticeTemplate.id)
            .all()
        )
        return [_tpl_dict(t) for t in rows]


# ── 템플릿 조회·수정 (라우터용) ─────────────────────────────────────────
def list_templates_db(db: Session, include_inactive: bool = False) -> list[dict]:
    q = db.query(NoticeTemplate)
    if not include_inactive:
        q = q.filter(NoticeTemplate.is_active.is_(True))
    rows = q.order_by(NoticeTemplate.sort_order, NoticeTemplate.id).all()
    return [_tpl_dict(t) for t in rows]


def get_template(db: Session, code: str) -> NoticeTemplate | None:
    return db.query(NoticeTemplate).filter(NoticeTemplate.code == code).first()


def create_template(db: Session, data: dict) -> dict:
    if data["intent_type"] not in TEMPLATE_INTENTS:
        raise StoreError("bad_intent", f"상황은 {TEMPLATE_INTENTS} 중 하나여야 합니다")
    if data.get("widget", "none") not in WIDGETS:
        raise StoreError("bad_widget", f"위젯은 {WIDGETS} 중 하나여야 합니다")
    if get_template(db, data["code"]):
        raise StoreError("duplicate_code", f"이미 있는 코드입니다: {data['code']}")

    t = NoticeTemplate(
        code=data["code"],
        intent_type=data["intent_type"],
        title=data["title"],
        text_ko=data.get("text_ko", ""),
        text_en=data.get("text_en", ""),
        text_zh=data.get("text_zh", ""),
        text_ja=data.get("text_ja", ""),
        pictogram=data.get("pictogram"),
        widget=data.get("widget", "none"),
        needs_duration=bool(data.get("needs_duration", False)),
        default_minutes=data.get("default_minutes"),
        trigger_haptic=bool(data.get("trigger_haptic", False)),
        # 화면에서 만든 템플릿은 기본 템플릿이 될 수 없다. 지울 수 있어야 하므로.
        is_default=False,
        sort_order=int(data.get("sort_order", 100)),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _tpl_dict(t)


_EDITABLE = (
    "intent_type", "title", "text_ko", "text_en", "text_zh", "text_ja",
    "pictogram", "widget", "needs_duration", "default_minutes",
    "trigger_haptic", "sort_order", "is_active",
)


def update_template(db: Session, code: str, data: dict) -> dict:
    t = get_template(db, code)
    if not t:
        raise StoreError("not_found", f"없는 템플릿입니다: {code}")
    if "intent_type" in data and data["intent_type"] not in TEMPLATE_INTENTS:
        raise StoreError("bad_intent", f"상황은 {TEMPLATE_INTENTS} 중 하나여야 합니다")
    if "widget" in data and data["widget"] not in WIDGETS:
        raise StoreError("bad_widget", f"위젯은 {WIDGETS} 중 하나여야 합니다")
    # 기본 템플릿은 숨길 수 없다. 불이 났는데 화재 템플릿이 목록에 없으면 안 된다.
    if t.is_default and data.get("is_active") is False:
        raise StoreError("default_protected", f"{t.title} 은(는) 숨길 수 없습니다")

    for key in _EDITABLE:
        if key in data:
            setattr(t, key, data[key])
    db.commit()
    db.refresh(t)
    return _tpl_dict(t)


def delete_template(db: Session, code: str) -> None:
    t = get_template(db, code)
    if not t:
        raise StoreError("not_found", f"없는 템플릿입니다: {code}")
    if t.is_default:
        raise StoreError("default_protected", f"{t.title} 은(는) 지울 수 없습니다")
    # 지난 공지가 template_id 로 이 줄을 가리키고 있다. 실제로 지우면 기록이 깨진다.
    t.is_active = False
    db.commit()


def list_pictograms(db: Session) -> list[dict]:
    rows = db.query(Pictogram).order_by(Pictogram.sort_order, Pictogram.id).all()
    return [{"name": p.name, "label_ko": p.label_ko, "file_name": p.file_name}
            for p in rows]


# ── 이벤트 ──────────────────────────────────────────────────────────────
def _append_event(db: Session, notice: Notice, kind: str) -> NoticeEvent:
    assert kind in EVENT_KINDS
    ev = NoticeEvent(notice_id=notice.id, kind=kind, snapshot=_notice_dict(notice))
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def _publish(ev: NoticeEvent) -> None:
    hub.broadcast(ev.id, {
        "event_id": ev.id,
        "kind": ev.kind,
        "notice": ev.snapshot,
    })


def events_after(last_id: int) -> list[dict]:
    """끊겼다 붙은 관객에게 놓친 것부터 보낸다. stream.py 가 부른다."""
    with SessionLocal() as db:
        rows = (
            db.query(NoticeEvent)
            .filter(NoticeEvent.id > int(last_id or 0))
            .order_by(NoticeEvent.id)
            .all()
        )
        return [{"event_id": e.id, "kind": e.kind, "snapshot": e.snapshot}
                for e in rows]


def to_sse_payload(event: dict) -> dict:
    """events_after() 가 준 것을 실시간 전송과 같은 모양으로 맞춘다."""
    return {
        "event_id": event["event_id"],
        "kind": event["kind"],
        "notice": event["snapshot"],
    }


# ── 공지 ────────────────────────────────────────────────────────────────
def get_active_notice(db: Session) -> Notice | None:
    return (
        db.query(Notice)
        .filter(Notice.status == "ACTIVE")
        .order_by(Notice.id.desc())
        .first()
    )


def _end(db: Session, notice: Notice) -> NoticeEvent:
    notice.status = "ENDED"
    notice.ended_at = now()
    db.commit()
    db.refresh(notice)
    return _append_event(db, notice, "ENDED")


def create_notice(db: Session, data: dict) -> dict:
    """
    공지를 만들어 송출한다. 송출 중인 공지가 있으면 먼저 종료한다.
    '덮어써도 되는가' 는 라우터에서 판단한 뒤 여기로 온다.
    """
    intent = data.get("intent_type")
    if intent not in TEMPLATE_INTENTS:
        raise StoreError("bad_intent", f"상황은 {TEMPLATE_INTENTS} 중 하나여야 합니다")

    code = data.get("template_code")
    tpl = get_template(db, code) if code else None
    if code and not tpl:
        raise StoreError("not_found", f"없는 템플릿입니다: {code}")

    minutes = data.get("minutes")
    if tpl and tpl.needs_duration and minutes is None:
        minutes = tpl.default_minutes
    if minutes is not None:
        minutes = int(minutes)
        if minutes <= 0:
            raise StoreError("bad_minutes", "분 수는 1 이상이어야 합니다")

    if tpl:
        texts = {lang: _fill_minutes(getattr(tpl, f"text_{lang}"), minutes)
                 for lang in ("ko", "en", "zh", "ja")}
        pictogram = data.get("pictogram") or tpl.pictogram
        widget = data.get("widget") or tpl.widget
        haptic = data.get("trigger_haptic")
        if haptic is None:
            haptic = tpl.trigger_haptic
    else:
        texts = {lang: (data.get(f"text_{lang}") or "") for lang in ("ko", "en", "zh", "ja")}
        pictogram = data.get("pictogram")
        widget = data.get("widget") or "none"
        # 직접 작성한 공지는 오퍼레이터가 일반/비상을 고른다 (11/15 회의).
        haptic = bool(data.get("trigger_haptic", False))

    if not texts["ko"].strip():
        raise StoreError("empty_text", "한국어 본문이 비어 있습니다")
    if widget not in WIDGETS:
        raise StoreError("bad_widget", f"위젯은 {WIDGETS} 중 하나여야 합니다")

    expires_at = None
    if widget == "timer" and minutes:
        expires_at = now() + timedelta(minutes=minutes)

    # 송출 중인 공지가 있으면 먼저 내린다. 한 번에 한 건만 보인다 (OP-03-9).
    active = get_active_notice(db)
    if active:
        ev_end = _end(db, active)
        _publish(ev_end)

    n = Notice(
        template_id=tpl.id if tpl else None,
        template_code=tpl.code if tpl else None,
        intent_type=intent,
        text_ko=texts["ko"], text_en=texts["en"],
        text_zh=texts["zh"], text_ja=texts["ja"],
        pictogram=pictogram,
        widget=widget,
        minutes=minutes,
        expires_at=expires_at,
        direction=data.get("direction"),   # 선택값 (11/17: 화재는 약도로 간다)
        trigger_haptic=bool(haptic),
        operator_name=data.get("operator_name"),
        status="ACTIVE",
        revision=0,
    )
    db.add(n)
    db.commit()
    db.refresh(n)

    ev = _append_event(db, n, "CREATED")
    _publish(ev)
    return _notice_dict(n)


def correct_notice(db: Session, notice_id: int, data: dict) -> dict:
    """
    정정 (OP-04). 템플릿과 상황까지 바꿀 수 있다.
    새 공지를 만들지 않고 같은 공지의 revision 을 올린다 — 관객 화면이 그대로 바뀐다.
    """
    n = db.query(Notice).filter(Notice.id == notice_id).first()
    if not n:
        raise StoreError("not_found", f"없는 공지입니다: {notice_id}")
    if n.status != "ACTIVE":
        raise StoreError("not_active", "이미 끝난 공지는 고칠 수 없습니다")

    if "intent_type" in data:
        if data["intent_type"] not in TEMPLATE_INTENTS:
            raise StoreError("bad_intent", f"상황은 {TEMPLATE_INTENTS} 중 하나여야 합니다")
        n.intent_type = data["intent_type"]

    # 템플릿을 갈아끼우면 문구·아이콘·위젯을 그 템플릿 것으로 다시 채운다.
    if "template_code" in data:
        code = data["template_code"]
        if code:
            tpl = get_template(db, code)
            if not tpl:
                raise StoreError("not_found", f"없는 템플릿입니다: {code}")
            minutes = data.get("minutes", n.minutes)
            if tpl.needs_duration and minutes is None:
                minutes = tpl.default_minutes
            n.template_id = tpl.id
            n.template_code = tpl.code
            n.intent_type = data.get("intent_type", tpl.intent_type)
            n.minutes = minutes
            for lang in ("ko", "en", "zh", "ja"):
                setattr(n, f"text_{lang}",
                        _fill_minutes(getattr(tpl, f"text_{lang}"), minutes))
            n.pictogram = tpl.pictogram
            n.widget = tpl.widget
            n.trigger_haptic = tpl.trigger_haptic
        else:
            n.template_id = None
            n.template_code = None

    for lang in ("ko", "en", "zh", "ja"):
        key = f"text_{lang}"
        if key in data:
            setattr(n, key, data[key] or "")
    for key in ("pictogram", "direction", "operator_name"):
        if key in data:
            setattr(n, key, data[key])
    if "minutes" in data:
        n.minutes = int(data["minutes"]) if data["minutes"] is not None else None
    if "widget" in data:
        if data["widget"] not in WIDGETS:
            raise StoreError("bad_widget", f"위젯은 {WIDGETS} 중 하나여야 합니다")
        n.widget = data["widget"]
    if "trigger_haptic" in data:
        n.trigger_haptic = bool(data["trigger_haptic"])

    if not (n.text_ko or "").strip():
        raise StoreError("empty_text", "한국어 본문이 비어 있습니다")

    n.expires_at = (now() + timedelta(minutes=n.minutes)
                    if n.widget == "timer" and n.minutes else None)
    n.revision += 1
    db.commit()
    db.refresh(n)

    ev = _append_event(db, n, "UPDATED")
    _publish(ev)
    return _notice_dict(n)


def end_notice(db: Session, notice_id: int) -> dict:
    n = db.query(Notice).filter(Notice.id == notice_id).first()
    if not n:
        raise StoreError("not_found", f"없는 공지입니다: {notice_id}")
    if n.status != "ACTIVE":
        return _notice_dict(n)   # 이미 끝났으면 조용히 통과시킨다
    ev = _end(db, n)
    _publish(ev)
    return _notice_dict(n)


def list_past_notices(db: Session, limit: int = 20, offset: int = 0) -> list[dict]:
    rows = (
        db.query(Notice)
        .order_by(Notice.id.desc())
        .limit(min(int(limit), 100))
        .offset(int(offset))
        .all()
    )
    return [_notice_dict(n) for n in rows]
