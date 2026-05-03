import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Agent, AuditLog, User
from schemas import UtcDatetimeModel

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])
audit_router = APIRouter(prefix="/api/admin", tags=["admin-audit-logs"])


class AdminUserResponse(UtcDatetimeModel):
    id: int
    username: str
    role: str
    status: str
    created_at: datetime | None
    last_login_at: datetime | None
    last_login_ip: str | None

    class Config:
        from_attributes = True


class UserRoleUpdateRequest(BaseModel):
    role: Literal["admin", "user"]
    confirm_publicize_agents: bool = False


class UserStatusUpdateRequest(BaseModel):
    status: Literal["active", "frozen"]


class AuditLogResponse(UtcDatetimeModel):
    id: int
    operator_id: int
    operator_username: str | None
    action: str
    target_type: str
    target_id: int
    detail: str | None
    created_at: datetime | None


def _count_active_admins(db: Session) -> int:
    return db.query(User).filter(User.role == "admin", User.status == "active").count()


def _get_target_user(db: Session, user_id: int) -> User:
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return target


@router.get("", response_model=list[AdminUserResponse])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.created_at.desc(), User.id.desc()).all()
    return [AdminUserResponse.model_validate(user) for user in users]


@router.put("/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: int,
    body: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _get_target_user(db, user_id)

    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色")

    if target.role == body.role:
        return AdminUserResponse.model_validate(target)

    if target.role == "admin" and body.role != "admin" and target.status == "active" and _count_active_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统至少需要保留一个激活状态的管理员")

    old_role = target.role

    migrated_agent_ids: list[int] = []
    if old_role == "admin" and body.role == "user":
        if target.username == "admin":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="超级管理员不可降级")
        super_admin = db.query(User).filter(User.username == "admin", User.role == "admin").first()
        if not super_admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到超级管理员，无法迁移公共 Agent")
        target_agents = db.query(Agent).filter(Agent.created_by == target.id).all()
        target_names = {agent.name for agent in target_agents}
        conflicts = (
            db.query(Agent)
            .filter(Agent.created_by == super_admin.id, Agent.name.in_(target_names))
            .all()
            if target_names
            else []
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Agent name conflicts prevent admin downgrade",
                    "conflicts": [
                        {"name": agent.name, "target_owner": target.username, "new_owner": super_admin.username}
                        for agent in conflicts
                    ],
                },
            )
        migrated_agent_ids = [agent.id for agent in target_agents]
        for agent in target_agents:
            agent.created_by = super_admin.id

    if old_role == "user" and body.role == "admin":
        target_agents = db.query(Agent).filter(Agent.created_by == target.id).order_by(Agent.id).all()
        if target_agents and not body.confirm_publicize_agents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Promoting this user will publicize their agents",
                    "requires_confirmation": True,
                    "agents": [{"id": agent.id, "name": agent.name} for agent in target_agents],
                },
            )

    target.role = body.role
    audit = AuditLog(
        operator_id=admin.id,
        action="user.role.update",
        target_type="user",
        target_id=user_id,
        detail=json.dumps(
            {
                "user_id": user_id,
                "old_role": old_role,
                "new_role": body.role,
                "migrated_agent_count": len(migrated_agent_ids),
                "migrated_agent_ids": migrated_agent_ids,
            },
            ensure_ascii=False,
        ),
    )
    db.add(audit)
    db.commit()
    db.refresh(target)
    return AdminUserResponse.model_validate(target)


@router.put("/{user_id}/status", response_model=AdminUserResponse)
def update_user_status(
    user_id: int,
    body: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = _get_target_user(db, user_id)

    if target.id == admin.id and body.status == "frozen":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能冻结自己")

    if target.status == body.status:
        return AdminUserResponse.model_validate(target)

    if target.role == "admin" and target.status == "active" and body.status == "frozen" and _count_active_admins(db) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统至少需要保留一个激活状态的管理员")

    old_status = target.status
    target.status = body.status
    audit = AuditLog(
        operator_id=admin.id,
        action="user.status.update",
        target_type="user",
        target_id=user_id,
        detail=json.dumps(
            {"user_id": user_id, "old_status": old_status, "new_status": body.status},
            ensure_ascii=False,
        ),
    )
    db.add(audit)
    db.commit()
    db.refresh(target)
    return AdminUserResponse.model_validate(target)


@audit_router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = (
        db.query(AuditLog, User.username)
        .join(User, User.id == AuditLog.operator_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.limit(limit).all()
    return [
        AuditLogResponse(
            id=audit.id,
            operator_id=audit.operator_id,
            operator_username=operator_username,
            action=audit.action,
            target_type=audit.target_type,
            target_id=audit.target_id,
            detail=audit.detail,
            created_at=audit.created_at,
        )
        for audit, operator_username in rows
    ]
