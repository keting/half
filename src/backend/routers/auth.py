import re
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, User
from config import settings as app_settings
from auth import verify_password, hash_password, create_token, get_current_user
from middleware.rate_limit import login_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

PASSWORD_PATTERN = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$')


def validate_password_strength(password: str) -> str:
    if not PASSWORD_PATTERN.match(password):
        raise ValueError(
            "密码必须至少6位，且包含大写字母、小写字母和数字"
        )
    return password


def _extract_client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else None


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 2:
            raise ValueError("用户名至少需要2个字符")
        if len(v) > 32:
            raise ValueError("用户名不能超过32个字符")
        return v

    @field_validator("password")
    @classmethod
    def password_strong(cls, v: str) -> str:
        return validate_password_strength(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class LoginResponse(BaseModel):
    token: str
    user_id: int
    username: str
    role: str
    status: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    status: str

    class Config:
        from_attributes = True


class AuthConfigResponse(BaseModel):
    allow_register: bool


@router.get("/config", response_model=AuthConfigResponse)
def get_auth_config():
    return AuthConfigResponse(allow_register=app_settings.ALLOW_REGISTER)


@router.post("/register", response_model=LoginResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if not app_settings.ALLOW_REGISTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Contact your administrator.",
        )
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该用户名已被注册",
        )
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="user",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id, user.username, user.role)
    return LoginResponse(token=token, user_id=user.id, username=user.username, role=user.role, status=user.status)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request = None, db: Session = Depends(get_db)):
    rate_key = f"login:{body.username}"
    login_limiter.check(rate_key)

    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        login_limiter.record_failure(rate_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if user.status == "frozen":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被冻结，请联系管理员")

    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = _extract_client_ip(request)
    db.commit()
    login_limiter.record_success(rate_key)
    token = create_token(user.id, user.username, user.role)
    return LoginResponse(token=token, user_id=user.id, username=user.username, role=user.role, status=user.status)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if body.current_password == body.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")

    user.password_hash = hash_password(body.new_password)
    audit = AuditLog(
        operator_id=user.id,
        action="user.password.change",
        target_type="user",
        target_id=user.id,
        detail=json.dumps({"user_id": user.id}, ensure_ascii=False),
    )
    db.add(audit)
    db.commit()
    return {"detail": "密码修改成功"}
