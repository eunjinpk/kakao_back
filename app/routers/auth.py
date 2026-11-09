"""
오퍼레이터 인증 — 더미 버전.

W1 후반에 bcrypt + JWT 로 교체한다.
교체해도 요청/응답 모양은 그대로라 프론트는 수정 불필요.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()

# 더미 계정 (W1 후반에 users 테이블로 이동)
DUMMY_USERS = {
    "operator": {"id": 1, "password": "test1234", "name": "오퍼레이터", "role": "operator"},
    "admin": {"id": 2, "password": "test1234", "name": "관리자", "role": "admin"},
}

_sessions: dict[str, dict] = {}


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/admin/login")
def login(body: LoginBody):
    user = DUMMY_USERS.get(body.username)
    if not user or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    token = f"dummy-token-{user['id']}"
    _sessions[token] = user
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
    }


def require_operator(authorization: str = Header(default="")) -> dict:
    """오퍼레이터 API 보호. Authorization: Bearer <token>"""
    token = authorization.removeprefix("Bearer ").strip()
    user = _sessions.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user
