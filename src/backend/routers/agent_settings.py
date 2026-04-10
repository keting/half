from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import AgentTypeConfig, ModelDefinition, AgentTypeModelMap, Agent
from auth import require_admin, User

router = APIRouter(prefix="/api/agent-settings", tags=["agent-settings"])


# --- Schemas ---

class ModelDefinitionOut(BaseModel):
    id: int
    name: str
    alias: Optional[str] = None
    capability: Optional[str] = None

    class Config:
        from_attributes = True


class AgentTypeOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    models: list[ModelDefinitionOut] = Field(default_factory=list)


class AgentTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None


class AgentTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ModelAddToType(BaseModel):
    name: str
    alias: Optional[str] = None
    capability: Optional[str] = None


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    alias: Optional[str] = None
    capability: Optional[str] = None


class ReorderTypesRequest(BaseModel):
    type_ids: list[int]


class ReorderModelsRequest(BaseModel):
    model_ids: list[int]


class ModelSearchResult(BaseModel):
    id: int
    name: str
    alias: Optional[str] = None
    capability: Optional[str] = None

    class Config:
        from_attributes = True


# --- Helpers ---

def _find_model_by_identity(db: Session, name: str, alias: Optional[str] = None, exclude_id: Optional[int] = None) -> Optional[ModelDefinition]:
    """Find an existing model where name or alias matches the given name or alias."""
    from sqlalchemy import or_, and_

    conditions = [ModelDefinition.name == name]
    conditions.append(and_(ModelDefinition.alias.isnot(None), ModelDefinition.alias == name))
    if alias:
        conditions.append(ModelDefinition.name == alias)
        conditions.append(and_(ModelDefinition.alias.isnot(None), ModelDefinition.alias == alias))

    query = db.query(ModelDefinition).filter(or_(*conditions))
    if exclude_id is not None:
        query = query.filter(ModelDefinition.id != exclude_id)
    return query.first()


def _build_agent_type_response(db: Session, agent_type: AgentTypeConfig) -> AgentTypeOut:
    maps = db.query(AgentTypeModelMap).filter(
        AgentTypeModelMap.agent_type_id == agent_type.id
    ).order_by(AgentTypeModelMap.display_order, AgentTypeModelMap.id).all()
    model_ids = [m.model_definition_id for m in maps]
    if model_ids:
        models_by_id = {m.id: m for m in db.query(ModelDefinition).filter(ModelDefinition.id.in_(model_ids)).all()}
        models = [models_by_id[mid] for mid in model_ids if mid in models_by_id]
    else:
        models = []
    return AgentTypeOut(
        id=agent_type.id,
        name=agent_type.name,
        description=agent_type.description,
        models=[ModelDefinitionOut.model_validate(m) for m in models],
    )


# --- Agent Type Endpoints ---

@router.get("/types", response_model=list[AgentTypeOut])
def list_agent_types(db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    types = db.query(AgentTypeConfig).order_by(AgentTypeConfig.display_order, AgentTypeConfig.id).all()
    return [_build_agent_type_response(db, t) for t in types]


@router.put("/types/reorder", response_model=list[AgentTypeOut])
def reorder_agent_types(body: ReorderTypesRequest, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    for index, type_id in enumerate(body.type_ids):
        t = db.query(AgentTypeConfig).filter(AgentTypeConfig.id == type_id).first()
        if t:
            t.display_order = index
    db.commit()
    types = db.query(AgentTypeConfig).order_by(AgentTypeConfig.display_order, AgentTypeConfig.id).all()
    return [_build_agent_type_response(db, t) for t in types]


@router.put("/types/{type_id}/models/reorder", response_model=AgentTypeOut)
def reorder_models_in_type(type_id: int, body: ReorderModelsRequest, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.id == type_id).first()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent 类型不存在")
    for index, model_id in enumerate(body.model_ids):
        mapping = db.query(AgentTypeModelMap).filter(
            AgentTypeModelMap.agent_type_id == type_id,
            AgentTypeModelMap.model_definition_id == model_id,
        ).first()
        if mapping:
            mapping.display_order = index
    db.commit()
    return _build_agent_type_response(db, agent_type)


@router.post("/types", response_model=AgentTypeOut, status_code=status.HTTP_201_CREATED)
def create_agent_type(body: AgentTypeCreate, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    existing = db.query(AgentTypeConfig).filter(AgentTypeConfig.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="该 Agent 类型已存在")
    agent_type = AgentTypeConfig(name=name, description=body.description)
    db.add(agent_type)
    db.commit()
    db.refresh(agent_type)
    return _build_agent_type_response(db, agent_type)


@router.put("/types/{type_id}", response_model=AgentTypeOut)
def update_agent_type(type_id: int, body: AgentTypeUpdate, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.id == type_id).first()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent 类型不存在")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="名称不能为空")
        dup = db.query(AgentTypeConfig).filter(AgentTypeConfig.name == name, AgentTypeConfig.id != type_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="该 Agent 类型名称已存在")
        # Update agent_type field on existing agents that used the old name
        old_name = agent_type.name
        if old_name != name:
            db.query(Agent).filter(Agent.agent_type == old_name).update({"agent_type": name})
        agent_type.name = name

    if body.description is not None:
        agent_type.description = body.description.strip() or None

    agent_type.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent_type)
    return _build_agent_type_response(db, agent_type)


@router.delete("/types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_type(type_id: int, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.id == type_id).first()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent 类型不存在")

    # Check if any agents use this type
    agent_ref = db.query(Agent).filter(Agent.agent_type == agent_type.name).first()
    if agent_ref:
        raise HTTPException(status_code=400, detail="该类型下还有已创建的 Agent，无法删除")

    # Remove model mappings
    db.query(AgentTypeModelMap).filter(AgentTypeModelMap.agent_type_id == type_id).delete()
    db.delete(agent_type)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Model Management within Agent Type ---

@router.post("/types/{type_id}/models", response_model=AgentTypeOut)
def add_model_to_type(type_id: int, body: ModelAddToType, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.id == type_id).first()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent 类型不存在")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    alias = body.alias.strip() if body.alias else None

    # Find existing model by identity (name/alias matching)
    model_def = _find_model_by_identity(db, name, alias)
    if model_def is None:
        # Create new model definition
        model_def = ModelDefinition(
            name=name,
            alias=alias,
            capability=body.capability[:150] if body.capability else None,
        )
        db.add(model_def)
        db.flush()
    else:
        # Update alias/capability if provided and model didn't have them
        if alias and not model_def.alias:
            model_def.alias = alias
        if body.capability and not model_def.capability:
            model_def.capability = body.capability[:150]

    # Check if mapping already exists
    existing_map = db.query(AgentTypeModelMap).filter(
        AgentTypeModelMap.agent_type_id == type_id,
        AgentTypeModelMap.model_definition_id == model_def.id,
    ).first()
    if existing_map:
        raise HTTPException(status_code=400, detail="该模型已添加到此 Agent 类型")

    db.add(AgentTypeModelMap(agent_type_id=type_id, model_definition_id=model_def.id))
    db.commit()
    db.refresh(agent_type)
    return _build_agent_type_response(db, agent_type)


@router.delete("/types/{type_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_model_from_type(type_id: int, model_id: int, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    mapping = db.query(AgentTypeModelMap).filter(
        AgentTypeModelMap.agent_type_id == type_id,
        AgentTypeModelMap.model_definition_id == model_id,
    ).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="映射不存在")
    db.delete(mapping)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Global Model Endpoints ---

@router.put("/models/{model_id}", response_model=ModelDefinitionOut)
def update_model_definition(model_id: int, body: ModelUpdate, db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    model_def = db.query(ModelDefinition).filter(ModelDefinition.id == model_id).first()
    if not model_def:
        raise HTTPException(status_code=404, detail="模型不存在")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        # Check uniqueness
        dup = db.query(ModelDefinition).filter(ModelDefinition.name == name, ModelDefinition.id != model_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="该模型名称已存在")
        model_def.name = name

    if body.alias is not None:
        alias = body.alias.strip() if body.alias else None
        # Check alias doesn't conflict with another model's name or alias
        if alias:
            conflict = _find_model_by_identity(db, alias, exclude_id=model_id)
            if conflict:
                raise HTTPException(
                    status_code=400,
                    detail=f"该别名与已有模型 \"{conflict.name}\" 冲突，系统将识别为同一模型"
                )
        model_def.alias = alias

    if body.capability is not None:
        model_def.capability = body.capability[:150] if body.capability else None

    model_def.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(model_def)
    return ModelDefinitionOut.model_validate(model_def)


@router.get("/models/search", response_model=list[ModelSearchResult])
def search_models(q: str = "", db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    """Search model definitions by name or alias for auto-complete."""
    if not q.strip():
        return db.query(ModelDefinition).order_by(ModelDefinition.name).limit(20).all()
    pattern = f"%{q.strip()}%"
    from sqlalchemy import or_
    return db.query(ModelDefinition).filter(
        or_(
            ModelDefinition.name.ilike(pattern),
            ModelDefinition.alias.ilike(pattern),
        )
    ).order_by(ModelDefinition.name).limit(20).all()


@router.get("/types/search", response_model=list[dict])
def search_agent_types(q: str = "", db: Session = Depends(get_db), _user: User = Depends(require_admin)):
    """Search agent type names for auto-complete."""
    query = db.query(AgentTypeConfig)
    if q.strip():
        query = query.filter(AgentTypeConfig.name.ilike(f"%{q.strip()}%"))
    types = query.order_by(AgentTypeConfig.name).limit(20).all()
    return [{"id": t.id, "name": t.name} for t in types]
