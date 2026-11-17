"""
템플릿 관리 (OP-09) — 화면에서 추가·수정·삭제한다.

기본 비상 템플릿(is_default)은 지우지도 숨기지도 못한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import store
from app.db import get_db

router = APIRouter()


class TemplateIn(BaseModel):
    code: str = Field(..., examples=["ETIQUETTE_BAG"])
    intent_type: str = Field(..., examples=["ETIQUETTE"])
    title: str = Field(..., examples=["가방 안내"])
    text_ko: str = ""
    text_en: str = ""
    text_zh: str = ""
    text_ja: str = ""
    pictogram: str | None = None
    widget: str = "none"
    needs_duration: bool = False
    default_minutes: int | None = None
    trigger_haptic: bool = False
    sort_order: int = 100


class TemplatePatch(BaseModel):
    intent_type: str | None = None
    title: str | None = None
    text_ko: str | None = None
    text_en: str | None = None
    text_zh: str | None = None
    text_ja: str | None = None
    pictogram: str | None = None
    widget: str | None = None
    needs_duration: bool | None = None
    default_minutes: int | None = None
    trigger_haptic: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


def _fail(e: store.StoreError):
    code_to_status = {
        "not_found": 404,
        "duplicate_code": 409,
        "default_protected": 409,
    }
    raise HTTPException(
        status_code=code_to_status.get(e.code, 400),
        detail={"code": e.code, "message": e.message, **e.extra},
    )


@router.get("/templates")
def get_templates(
    include_inactive: bool = Query(False, description="숨긴 템플릿도 포함"),
    db: Session = Depends(get_db),
):
    return {"templates": store.list_templates_db(db, include_inactive)}


@router.post("/templates", status_code=201)
def post_template(body: TemplateIn, db: Session = Depends(get_db)):
    try:
        return store.create_template(db, body.model_dump())
    except store.StoreError as e:
        _fail(e)


@router.patch("/templates/{code}")
def patch_template(code: str, body: TemplatePatch, db: Session = Depends(get_db)):
    try:
        # 보낸 필드만 바꾼다. 안 보낸 필드는 그대로 둔다.
        return store.update_template(db, code, body.model_dump(exclude_unset=True))
    except store.StoreError as e:
        _fail(e)


@router.delete("/templates/{code}")
def remove_template(code: str, db: Session = Depends(get_db)):
    """
    실제로 지우지 않고 숨긴다(is_active=False).
    지난 공지가 이 템플릿을 가리키고 있어서, 진짜 지우면 기록이 깨진다.
    """
    try:
        store.delete_template(db, code)
    except store.StoreError as e:
        _fail(e)
    return {"ok": True, "code": code}


@router.get("/pictograms")
def get_pictograms(db: Session = Depends(get_db)):
    return {"pictograms": store.list_pictograms(db)}
