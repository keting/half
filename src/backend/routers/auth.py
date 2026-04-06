import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import verify_password, hash_password, create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

PASSWORD_PATTERN = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$')


def validate_password_strength(password: str) -> str:
    if not PASSWORD_PATTERN.match(password):
        raise ValueError(
            "密码必须至少6位，且包含大写字母、小写字母和数字"
        )
    return password


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


class LoginResponse(BaseModel):
    token: str
    user_id: int
    username: str


class UserResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


@router.post("/register", response_model=LoginResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该用户名已被注册",
        )
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id, user.username)
    return LoginResponse(token=token, user_id=user.id, username=user.username)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_token(user.id, user.username)
    return LoginResponse(token=token, user_id=user.id, username=user.username)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
