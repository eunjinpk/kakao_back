"""
공지 송출·정정·종료.

한 번에 한 건만 보인다 (OP-03-9). 송출 중인 공지가 있으면 409 를 돌려주고,
프론트가 확인 팝업을 띄운 뒤 replace_active=true 로 다시 보낸다.

화재는 예외가 둘이다.
  - 화재가 들어오면 확인 없이 기존 공지를 끊고 나간다.
  - 화재가 떠 있는 동안에는 어떤 공지도 밀어낼 수 없다. [종료]로만 내린다.
    (대피 안내 위에 "휴대폰 꺼주세요" 가 덮이면 안 되므로)

라우터가 전부 async def 인 이유: 공지를 바꾸면 관객 SSE 큐에 밀어넣는데,
그 큐는 이벤트 루프 안에서 건드려야 안전하다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import store
from app.db import get_db

router = APIRouter()


class NoticeIn(BaseModel):
    intent_type: str = Field(..., examples=["DELAY"])
    template_code: str | None = Field(None, examples=["SHOW_DELAY"])

    # 직접 작성할 때만 채운다. 템플릿을 쓰면 템플릿 문구가 들어간다.
    text_ko: str | None = None
    text_en: str | None = None
    text_zh: str | None = None
    text_ja: str | None = None

    minutes: int | None = Field(None, examples=[10])
    pictogram: str | None = None
    widget: str | None = Field(None, description="none | timer | map")
    direction: str | None = Field(None, description="LEFT | RIGHT | FRONT | REAR (선택)")

    # 직접 작성한 공지는 오퍼레이터가 일반/비상을 고른다 (11/15 회의).
    trigger_haptic: bool | None = None
    operator_name: str | None = None

    # 송출 중인 공지를 끊고 내보낼지. 프론트가 확인 팝업 뒤에 true 로 다시 보낸다.
    replace_active: bool = False


class NoticePatch(BaseModel):
    intent_type: str | None = None
    template_code: str | None = None
    text_ko: str | None = None
    text_en: str | None = None
    text_zh: str | None = None
    text_ja: str | None = None
    minutes: int | None = None
    pictogram: str | None = None
    widget: str | None = None
    direction: str | None = None
    trigger_haptic: bool | None = None
    operator_name: str | None = None


def _fail(e: store.StoreError):
    status = 404 if e.code == "not_found" else 400
    raise HTTPException(status_code=status,
                        detail={"code": e.code, "message": e.message, **e.extra})


@router.post("/notices", status_code=201)
async def post_notice(body: NoticeIn, db: Session = Depends(get_db)):
    active = store.get_active_notice(db)

    if active:
        if active.intent_type == "FIRE":
            raise HTTPException(409, detail={
                "code": "fire_active",
                "message": "화재 대피 안내가 송출 중입니다. [종료] 후에 보낼 수 있습니다.",
                "active_notice_id": active.id,
            })
        if body.intent_type != "FIRE" and not body.replace_active:
            raise HTTPException(409, detail={
                "code": "active_exists",
                "message": "이미 송출 중인 공지가 있습니다. 바꾸시겠습니까?",
                "active_notice_id": active.id,
                "active_text_ko": active.text_ko,
            })

    try:
        data = body.model_dump(exclude_unset=True)
        data.pop("replace_active", None)
        return store.create_notice(db, data)
    except store.StoreError as e:
        _fail(e)


@router.patch("/notices/{notice_id}")
async def patch_notice(notice_id: int, body: NoticePatch, db: Session = Depends(get_db)):
    """정정 (OP-04). 템플릿과 상황까지 바꿀 수 있다."""
    try:
        return store.correct_notice(db, notice_id, body.model_dump(exclude_unset=True))
    except store.StoreError as e:
        _fail(e)


@router.post("/notices/{notice_id}/end")
async def end_notice(notice_id: int, db: Session = Depends(get_db)):
    try:
        return store.end_notice(db, notice_id)
    except store.StoreError as e:
        _fail(e)


@router.get("/notices/active")
def get_active(db: Session = Depends(get_db)):
    """
    관객 기기가 처음 붙었을 때 부른다. 지금 떠 있어야 할 공지를 알려준다.
    없으면 notice 가 null.
    """
    n = store.get_active_notice(db)
    return {"notice": store._notice_dict(n) if n else None}


@router.get("/notices/past")
def get_past(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """지난 공지 (AU-06)."""
    return {"notices": store.list_past_notices(db, limit, offset)}
