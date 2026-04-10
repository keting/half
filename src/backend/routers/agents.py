import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from access import get_owned_agent, list_owned_agents
from database import get_db
from models import Agent, Project, Task, User, AgentTypeConfig, AgentTypeModelMap, ModelDefinition
from auth import get_current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])
BEIJING_TZ = timezone(timedelta(hours=8))


class AgentModelConfig(BaseModel):
    model_name: str
    capability: Optional[str] = None


class AgentCreate(BaseModel):
    name: str
    agent_type: str
    model_name: Optional[str] = None
    capability: Optional[str] = None
    models: list[AgentModelConfig] = Field(default_factory=list)
    machine_label: Optional[str] = None
    is_active: bool = True
    availability_status: str = "unknown"
    subscription_expires_at: Optional[datetime] = None
    short_term_reset_at: Optional[datetime] = None
    short_term_reset_interval_hours: Optional[int] = None
    long_term_reset_at: Optional[datetime] = None
    long_term_reset_interval_days: Optional[int] = None
    long_term_reset_mode: str = "days"


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    agent_type: Optional[str] = None
    model_name: Optional[str] = None
    capability: Optional[str] = None
    models: Optional[list[AgentModelConfig]] = None
    machine_label: Optional[str] = None
    is_active: Optional[bool] = None
    availability_status: Optional[str] = None
    subscription_expires_at: Optional[datetime] = None
    short_term_reset_at: Optional[datetime] = None
    short_term_reset_interval_hours: Optional[int] = None
    long_term_reset_at: Optional[datetime] = None
    long_term_reset_interval_days: Optional[int] = None
    long_term_reset_mode: Optional[str] = None


class StatusUpdate(BaseModel):
    availability_status: str


class ReorderRequest(BaseModel):
    agent_ids: list[int]


class AgentResponse(BaseModel):
    id: int
    name: str
    slug: str
    agent_type: str
    model_name: Optional[str]
    models: list[AgentModelConfig] = Field(default_factory=list)
    capability: Optional[str]
    machine_label: Optional[str]
    is_active: bool
    availability_status: str
    display_order: int = 0
    subscription_expires_at: Optional[datetime]
    short_term_reset_at: Optional[datetime]
    short_term_reset_interval_hours: Optional[int]
    short_term_reset_needs_confirmation: bool
    long_term_reset_at: Optional[datetime]
    long_term_reset_interval_days: Optional[int]
    long_term_reset_mode: str = "days"
    long_term_reset_needs_confirmation: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class AgentTypeCatalogModel(BaseModel):
    id: int
    name: str
    alias: Optional[str] = None
    capability: Optional[str] = None


class AgentTypeCatalogResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    models: list[AgentTypeCatalogModel] = Field(default_factory=list)


def _slugify(name: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized or "agent"



def _generate_unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    candidate = base
    index = 2
    while db.query(Agent).filter(Agent.slug == candidate).first():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _parse_agent_models(agent: Agent) -> list[AgentModelConfig]:
    if agent.models_json:
        try:
            parsed = json.loads(agent.models_json)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            models: list[AgentModelConfig] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                model_name = str(item.get("model_name") or "").strip()
                if not model_name:
                    continue
                capability = item.get("capability")
                models.append(
                    AgentModelConfig(
                        model_name=model_name,
                        capability=str(capability).strip() if capability else None,
                    )
                )
            if models:
                return models
    if agent.model_name:
        return [AgentModelConfig(model_name=agent.model_name, capability=agent.capability)]
    return []


def _build_agent_type_catalog(db: Session, agent_type: AgentTypeConfig) -> AgentTypeCatalogResponse:
    mappings = db.query(AgentTypeModelMap).filter(
        AgentTypeModelMap.agent_type_id == agent_type.id,
    ).order_by(AgentTypeModelMap.display_order, AgentTypeModelMap.id).all()
    model_ids = [item.model_definition_id for item in mappings]
    models_by_id = {
        model.id: model
        for model in db.query(ModelDefinition).filter(ModelDefinition.id.in_(model_ids)).all()
    } if model_ids else {}
    models = [
        AgentTypeCatalogModel(
            id=model.id,
            name=model.name,
            alias=model.alias,
            capability=model.capability,
        )
        for model_id in model_ids
        if (model := models_by_id.get(model_id)) is not None
    ]
    return AgentTypeCatalogResponse(
        id=agent_type.id,
        name=agent_type.name,
        description=agent_type.description,
        models=models,
    )


def _normalize_models_payload(
    models: Optional[list],
    fallback_model_name: Optional[str],
    fallback_capability: Optional[str],
) -> list[dict]:
    normalized: list[dict] = []
    for model in models or []:
        if isinstance(model, dict):
            raw_name = model.get("model_name", "")
            raw_cap = model.get("capability")
        else:
            raw_name = model.model_name
            raw_cap = model.capability
        model_name = (raw_name or "").strip()
        if not model_name:
            continue
        capability = raw_cap.strip() if raw_cap else None
        normalized.append({"model_name": model_name, "capability": capability or None})
    if normalized:
        return normalized
    fallback_name = (fallback_model_name or "").strip()
    if fallback_name:
        return [{
            "model_name": fallback_name,
            "capability": fallback_capability.strip() if fallback_capability else None,
        }]
    return []


def _derive_primary_fields_from_models(models: list[dict]) -> tuple[Optional[str], Optional[str]]:
    if not models:
        return None, None
    primary_model = models[0]["model_name"]
    capabilities = [model["capability"] for model in models if model.get("capability")]
    if not capabilities:
        return primary_model, None
    if len(capabilities) == 1:
        return primary_model, capabilities[0]
    return primary_model, "；".join(capabilities)


def _normalize_beijing_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(second=0, microsecond=0)
    return value.astimezone(BEIJING_TZ).replace(tzinfo=None, second=0, microsecond=0)


def _normalize_agent_input(payload: dict) -> dict:
    # Only touch model fields when model-related data is explicitly provided,
    # so that partial updates (e.g. status-only) never wipe existing models.
    has_model_fields = "models" in payload or "model_name" in payload or "capability" in payload
    if has_model_fields:
        normalized_models = _normalize_models_payload(
            payload.get("models"),
            payload.get("model_name"),
            payload.get("capability"),
        )
        payload["models_json"] = json.dumps(normalized_models, ensure_ascii=False)
        payload["model_name"], payload["capability"] = _derive_primary_fields_from_models(normalized_models)
        payload.pop("models", None)
    for field in ("short_term_reset_at", "long_term_reset_at"):
        if field in payload:
            payload[field] = _normalize_beijing_datetime(payload[field])
    return payload


def _normalize_agent_update_input(payload: dict) -> dict:
    """Normalize partial update payload without wiping model fields that were
    not explicitly edited by the caller."""
    for field in ("short_term_reset_at", "long_term_reset_at"):
        if field in payload:
            payload[field] = _normalize_beijing_datetime(payload[field])

    if "models" in payload:
        normalized_models = _normalize_models_payload(
            payload.get("models"),
            payload.get("model_name"),
            payload.get("capability"),
        )
        payload["models_json"] = json.dumps(normalized_models, ensure_ascii=False)
        payload["model_name"], payload["capability"] = _derive_primary_fields_from_models(normalized_models)
        payload.pop("models", None)
        return payload

    if "model_name" in payload:
        payload["model_name"] = (payload.get("model_name") or "").strip() or None
    if "capability" in payload:
        raw_capability = payload.get("capability")
        payload["capability"] = raw_capability.strip() if raw_capability else None

    return payload


def _now_beijing_naive() -> datetime:
    return datetime.now(BEIJING_TZ).replace(tzinfo=None, second=0, microsecond=0)


def _advance_reset_time(current: Optional[datetime], interval: Optional[int], *, hours: bool) -> Optional[datetime]:
    if not current or not interval or interval <= 0:
        return current
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TZ)
    else:
        current = current.astimezone(BEIJING_TZ)
    now = datetime.now(BEIJING_TZ)
    step = timedelta(hours=interval) if hours else timedelta(days=interval)
    while current <= now:
        current = current + step
    return current.replace(tzinfo=None)


def _same_day_next_month(dt: datetime) -> datetime:
    """Return the same day/time in the next month. If the day doesn't exist
    in the next month (e.g. 31st), clamp to the last day of that month."""
    import calendar
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)
    return dt.replace(year=year, month=month, day=day)


def _advance_reset_time_monthly(current: Optional[datetime]) -> Optional[datetime]:
    """Advance to the same day/time of the next month (preserving day and time)."""
    if not current:
        return current
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TZ)
    else:
        current = current.astimezone(BEIJING_TZ)
    now = datetime.now(BEIJING_TZ)
    while current <= now:
        current = _same_day_next_month(current)
    return current.replace(tzinfo=None)


def _normalize_agent_reset_times(agent: Agent, *, mark_confirmation: bool) -> bool:
    next_short = _advance_reset_time(agent.short_term_reset_at, agent.short_term_reset_interval_hours, hours=True)
    mode = getattr(agent, "long_term_reset_mode", None) or "days"
    if mode == "monthly":
        next_long = _advance_reset_time_monthly(agent.long_term_reset_at)
    else:
        next_long = _advance_reset_time(agent.long_term_reset_at, agent.long_term_reset_interval_days, hours=False)
    changed = next_short != agent.short_term_reset_at or next_long != agent.long_term_reset_at
    if changed:
        if mark_confirmation and next_short != agent.short_term_reset_at:
            agent.short_term_reset_needs_confirmation = True
            if getattr(agent, "availability_status", None) == "short_reset_pending":
                agent.availability_status = "available"
        if mark_confirmation and next_long != agent.long_term_reset_at:
            agent.long_term_reset_needs_confirmation = True
            if getattr(agent, "availability_status", None) == "long_reset_pending":
                agent.availability_status = "available"
        agent.short_term_reset_at = next_short
        agent.long_term_reset_at = next_long
        agent.updated_at = datetime.now(timezone.utc)
    return changed


def _clear_confirmation_flags_on_manual_update(agent: Agent, update_data: dict):
    if "short_term_reset_at" in update_data or "short_term_reset_interval_hours" in update_data:
        agent.short_term_reset_needs_confirmation = False
    if "long_term_reset_at" in update_data or "long_term_reset_interval_days" in update_data or "long_term_reset_mode" in update_data:
        agent.long_term_reset_needs_confirmation = False


def _build_agent_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        slug=agent.slug,
        agent_type=agent.agent_type,
        model_name=agent.model_name,
        models=_parse_agent_models(agent),
        capability=agent.capability,
        machine_label=agent.machine_label,
        is_active=agent.is_active,
        availability_status=agent.availability_status,
        display_order=agent.display_order or 0,
        subscription_expires_at=agent.subscription_expires_at,
        short_term_reset_at=agent.short_term_reset_at,
        short_term_reset_interval_hours=agent.short_term_reset_interval_hours,
        short_term_reset_needs_confirmation=agent.short_term_reset_needs_confirmation,
        long_term_reset_at=agent.long_term_reset_at,
        long_term_reset_interval_days=agent.long_term_reset_interval_days,
        long_term_reset_mode=agent.long_term_reset_mode or "days",
        long_term_reset_needs_confirmation=agent.long_term_reset_needs_confirmation,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )



@router.get("", response_model=list[AgentResponse])
def list_agents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agents = list_owned_agents(db, user)
    changed = False
    for agent in agents:
        changed = _normalize_agent_reset_times(agent, mark_confirmation=True) or changed
    if changed:
        db.commit()
        for agent in agents:
            db.refresh(agent)
    return [_build_agent_response(agent) for agent in agents]


@router.get("/config/types", response_model=list[AgentTypeCatalogResponse])
def list_agent_type_catalog(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    agent_types = db.query(AgentTypeConfig).order_by(AgentTypeConfig.display_order, AgentTypeConfig.id).all()
    return [_build_agent_type_catalog(db, agent_type) for agent_type in agent_types]


@router.put("/reorder", response_model=list[AgentResponse])
def reorder_agents(body: ReorderRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_ids = {
        row[0]
        for row in db.query(Agent.id).filter(Agent.created_by == user.id).all()
    }
    if any(agent_id not in owned_ids for agent_id in body.agent_ids):
        raise HTTPException(status_code=400, detail="Some agent_ids are invalid")
    for index, agent_id in enumerate(body.agent_ids):
        agent = db.query(Agent).filter(Agent.id == agent_id, Agent.created_by == user.id).first()
        if agent:
            agent.display_order = index
    db.commit()
    agents = list_owned_agents(db, user)
    for agent in agents:
        _normalize_agent_reset_times(agent, mark_confirmation=True)
    db.commit()
    for agent in agents:
        db.refresh(agent)
    return [_build_agent_response(agent) for agent in agents]


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(body: AgentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    existing = db.query(Agent).filter(
        Agent.name == body.name.strip(),
        Agent.created_by == user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Agent with name '{body.name.strip()}' already exists")
    payload = _normalize_agent_input(body.model_dump())
    payload["slug"] = _generate_unique_slug(db, body.name)
    payload["created_by"] = user.id
    agent = Agent(**payload)
    if agent.created_by is None:
        raise HTTPException(status_code=500, detail="created_by must not be None")
    _normalize_agent_reset_times(agent, mark_confirmation=False)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent(agent_id: int, body: AgentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)
    update_data = _normalize_agent_update_input(body.model_dump(exclude_unset=True))
    for key, value in update_data.items():
        setattr(agent, key, value)
    _clear_confirmation_flags_on_manual_update(agent, update_data)
    _normalize_agent_reset_times(agent, mark_confirmation=False)
    # If subscription was renewed (future date), auto-set status to available
    if "subscription_expires_at" in update_data and agent.subscription_expires_at:
        if agent.subscription_expires_at > _now_beijing_naive():
            if agent.availability_status in ("expired", "unknown"):
                agent.availability_status = "available"
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.patch("/{agent_id}/status", response_model=AgentResponse)
def update_agent_status(agent_id: int, body: StatusUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Only modify availability_status. Must NOT call _normalize_agent_input or touch
    model_name / models_json / capability — status changes are isolated from model config."""
    agent = get_owned_agent(db, agent_id, user)
    # Block status change if subscription expired
    if agent.subscription_expires_at and agent.subscription_expires_at <= _now_beijing_naive():
        raise HTTPException(status_code=400, detail="订阅已过期，无法更改状态")
    valid_statuses = ("available", "short_reset_pending", "long_reset_pending")
    if body.availability_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态，允许的值：{', '.join(valid_statuses)}")
    agent.availability_status = body.availability_status
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.post("/{agent_id}/short-term-reset/reset", response_model=AgentResponse)
def reset_short_term(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)
    if not agent.short_term_reset_at or not agent.short_term_reset_interval_hours:
        raise HTTPException(status_code=400, detail="短期重置时间或间隔未设置")
    agent.short_term_reset_at = _now_beijing_naive() + timedelta(hours=agent.short_term_reset_interval_hours)
    agent.short_term_reset_needs_confirmation = False
    agent.availability_status = "available"
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.post("/{agent_id}/short-term-reset/confirm", response_model=AgentResponse)
def confirm_short_term(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)
    agent.short_term_reset_needs_confirmation = False
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.post("/{agent_id}/long-term-reset/reset", response_model=AgentResponse)
def reset_long_term(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)
    mode = agent.long_term_reset_mode or "days"
    if not agent.long_term_reset_at:
        raise HTTPException(status_code=400, detail="长期重置时间未设置")
    if mode == "days" and not agent.long_term_reset_interval_days:
        raise HTTPException(status_code=400, detail="长期重置间隔未设置")
    if mode == "monthly":
        current_bj = agent.long_term_reset_at.replace(tzinfo=BEIJING_TZ) if agent.long_term_reset_at.tzinfo is None else agent.long_term_reset_at.astimezone(BEIJING_TZ)
        agent.long_term_reset_at = _same_day_next_month(current_bj).replace(tzinfo=None)
    else:
        agent.long_term_reset_at = _now_beijing_naive() + timedelta(days=agent.long_term_reset_interval_days)
    agent.long_term_reset_needs_confirmation = False
    # 长期重置同时触发短期重置
    if agent.short_term_reset_at and agent.short_term_reset_interval_hours:
        agent.short_term_reset_at = _now_beijing_naive() + timedelta(hours=agent.short_term_reset_interval_hours)
        agent.short_term_reset_needs_confirmation = False
    agent.availability_status = "available"
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.post("/{agent_id}/long-term-reset/confirm", response_model=AgentResponse)
def confirm_long_term(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)
    agent.long_term_reset_needs_confirmation = False
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)
    return _build_agent_response(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agent = get_owned_agent(db, agent_id, user)

    task_ref = db.query(Task).join(
        Project,
        Project.id == Task.project_id,
    ).filter(
        Task.assignee_agent_id == agent_id,
        Project.created_by == user.id,
    ).first()
    if task_ref:
        raise HTTPException(status_code=400, detail="Agent 已关联任务，无法删除")

    for project in db.query(Project).filter(Project.created_by == user.id).all():
        agent_ids = json.loads(project.agent_ids_json or "[]")
        if agent_id in agent_ids:
            raise HTTPException(status_code=400, detail="Agent 已关联项目，无法删除")

    db.delete(agent)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
