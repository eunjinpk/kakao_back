"""
테이블 정의 + 상황(intent) 상수.

테이블은 4개뿐이다.
  pictograms       아이콘 목록 (템플릿 만들 때 고른다)
  notice_templates 템플릿 (OP-09 에서 화면으로 추가·수정·삭제)
  notices          실제로 송출된 공지
  notice_events    공지의 변화 기록 — SSE 재전송에 쓴다
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)

from app.db import Base


def now() -> datetime:
    """DB 에는 UTC 를 tz 없이 넣는다. 비교가 단순해진다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── 상황 ────────────────────────────────────────────────────────────────
# AI 가 판단하는 것. 확실하지 않으면 NONE 을 낸다 (추천 없음 → 직접 작성).
LLM_INTENTS = (
    "FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE", "NONE",
)

# 템플릿이 가질 수 있는 것. INFO(일반 안내)는 AI 가 분류하지 않는다 (11/17 확정).
TEMPLATE_INTENTS = (
    "FIRE", "POWER_OUT", "PAUSE", "DELAY", "INTERMISSION", "ETIQUETTE", "INFO",
)

# 숫자가 작을수록 급하다. 템플릿 sort_order 의 기준값이기도 하다.
PRIORITY = {
    "FIRE": 10,
    "POWER_OUT": 20,
    "PAUSE": 30,
    "DELAY": 40,
    "INTERMISSION": 50,
    "ETIQUETTE": 60,
    "INFO": 70,
}

# 진동+점멸이 기본으로 켜지는 상황. 그 외는 오퍼레이터가 직접 고른다 (11/15 회의).
HAPTIC_INTENTS = ("FIRE",)

# 관객 화면에 같이 뜨는 것. timer=카운트다운, map=대피 약도
WIDGETS = ("none", "timer", "map")

NOTICE_STATUS = ("ACTIVE", "ENDED")
EVENT_KINDS = ("CREATED", "UPDATED", "ENDED")


# ── 테이블 ──────────────────────────────────────────────────────────────
class Pictogram(Base):
    __tablename__ = "pictograms"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)   # fire_exit
    label_ko = Column(String(50), nullable=False)            # 비상구
    file_name = Column(String(100))                          # fire_exit.svg
    sort_order = Column(Integer, nullable=False, default=100)


class NoticeTemplate(Base):
    """미리 만들어 둔 공지 문구. 화면에서 추가·수정·삭제할 수 있다 (OP-09)."""
    __tablename__ = "notice_templates"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    intent_type = Column(String(20), nullable=False, index=True)
    title = Column(String(100), nullable=False)

    text_ko = Column(Text, nullable=False)
    text_en = Column(Text, nullable=False, default="")
    text_zh = Column(Text, nullable=False, default="")
    text_ja = Column(Text, nullable=False, default="")

    pictogram = Column(String(50))
    widget = Column(String(10), nullable=False, default="none")

    # 분 수를 '입력칸에서 받을지'. 카운트다운을 띄울지(widget=timer)와는 별개다.
    #   지연·중단  needs_duration=True,  widget=none   → 본문에만 "20분"
    #   인터미션    needs_duration=True,  widget=timer  → 본문 + 카운트다운
    needs_duration = Column(Boolean, nullable=False, default=False)
    default_minutes = Column(Integer)

    trigger_haptic = Column(Boolean, nullable=False, default=False)

    # 기본 비상 템플릿. 지우지도, 숨기지도 못한다.
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    sort_order = Column(Integer, nullable=False, default=100)

    created_at = Column(DateTime, nullable=False, default=now)
    updated_at = Column(DateTime, nullable=False, default=now, onupdate=now)


class Notice(Base):
    """실제로 관객에게 나간 공지."""
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True)

    # 직접 작성한 공지는 둘 다 비어 있다.
    template_id = Column(Integer, ForeignKey("notice_templates.id"))
    template_code = Column(String(50))

    intent_type = Column(String(20), nullable=False)

    # 송출 시점의 문구를 그대로 박아 둔다.
    # 템플릿을 나중에 고쳐도 지난 공지의 기록은 바뀌지 않아야 한다.
    text_ko = Column(Text, nullable=False)
    text_en = Column(Text, nullable=False, default="")
    text_zh = Column(Text, nullable=False, default="")
    text_ja = Column(Text, nullable=False, default="")

    pictogram = Column(String(50))
    widget = Column(String(10), nullable=False, default="none")

    minutes = Column(Integer)
    expires_at = Column(DateTime)   # 타이머 끝나는 '절대 시각'

    # 대피 방향. 약도(widget=map)로 가기로 해서 필수가 아니다 (11/17).
    direction = Column(String(10))  # LEFT | RIGHT | FRONT | REAR

    trigger_haptic = Column(Boolean, nullable=False, default=False)
    operator_name = Column(String(50))   # 로그인이 없어서 이름만 남긴다

    status = Column(String(10), nullable=False, default="ACTIVE", index=True)
    revision = Column(Integer, nullable=False, default=0)   # 정정할 때마다 +1

    created_at = Column(DateTime, nullable=False, default=now)
    ended_at = Column(DateTime)


class NoticeEvent(Base):
    """
    공지가 생기고·고쳐지고·끝난 기록.

    id 가 곧 SSE 의 event id 다. 관객 기기가 끊겼다 붙으면
    Last-Event-ID 로 이 번호를 보내고, 그 뒤 기록을 전부 받아 따라잡는다.

    공지 id 를 쓰면 안 되는 이유: 같은 공지의 '생성'과 '종료'가
    같은 번호가 되어 버려서 둘 중 하나를 못 받는다.
    """
    __tablename__ = "notice_events"

    id = Column(Integer, primary_key=True)
    notice_id = Column(Integer, ForeignKey("notices.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)   # CREATED | UPDATED | ENDED

    # 그 시점의 공지 전체. 나중에 공지가 바뀌어도 이 기록은 그대로다.
    snapshot = Column(JSON, nullable=False)

    created_at = Column(DateTime, nullable=False, default=now)
