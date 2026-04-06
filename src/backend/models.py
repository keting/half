from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint,
)
from database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    slug = Column(Text, unique=True, nullable=False)
    agent_type = Column(Text, nullable=False)
    model_name = Column(Text)
    models_json = Column(Text, default="[]")
    capability = Column(Text)
    machine_label = Column(Text)
    is_active = Column(Boolean, default=True)
    availability_status = Column(Text, default="unknown")  # online/quota_exhausted/expired/unknown
    subscription_expires_at = Column(DateTime, nullable=True)
    short_term_reset_at = Column(DateTime, nullable=True)
    short_term_reset_interval_hours = Column(Integer, nullable=True)
    short_term_reset_needs_confirmation = Column(Boolean, default=False)
    long_term_reset_at = Column(DateTime, nullable=True)
    long_term_reset_interval_days = Column(Integer, nullable=True)
    long_term_reset_mode = Column(Text, default="days")  # days / monthly
    long_term_reset_needs_confirmation = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    last_usage_update_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    goal = Column(Text)
    git_repo_url = Column(Text)
    collaboration_dir = Column(Text)
    status = Column(Text, default="draft")  # draft/planning/executing/completed/abandoned
    agent_ids_json = Column(Text, default="[]")  # JSON array of agent IDs participating in project
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectPlan(Base):
    __tablename__ = "project_plans"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    source_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    plan_type = Column(Text, default="candidate")  # candidate/final
    plan_json = Column(Text)
    prompt_text = Column(Text)
    status = Column(Text, default="pending")  # pending/running/completed/needs_attention/final
    source_path = Column(Text)
    include_usage = Column(Boolean, default=False)
    selected_agent_ids_json = Column(Text, default="[]")
    selected_agent_models_json = Column(Text, default="{}")
    dispatched_at = Column(DateTime, nullable=True)
    detected_at = Column(DateTime, nullable=True)
    last_error = Column(Text)
    is_selected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "task_code", name="uq_task_project_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("project_plans.id"), nullable=False)
    task_code = Column(Text, nullable=False)
    task_name = Column(Text, nullable=False)
    description = Column(Text)
    assignee_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    status = Column(Text, default="pending")  # pending/running/completed/needs_attention/abandoned
    depends_on_json = Column(Text, default="[]")
    expected_output_path = Column(Text)
    result_file_path = Column(Text)
    usage_file_path = Column(Text)
    last_error = Column(Text)
    timeout_minutes = Column(Integer, default=10)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AgentTypeConfig(Base):
    __tablename__ = "agent_type_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ModelDefinition(Base):
    __tablename__ = "model_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, unique=True, nullable=False)
    alias = Column(Text, nullable=True)
    capability = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AgentTypeModelMap(Base):
    __tablename__ = "agent_type_model_map"
    __table_args__ = (
        UniqueConstraint("agent_type_id", "model_definition_id", name="uq_type_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    agent_type_id = Column(Integer, ForeignKey("agent_type_configs.id", ondelete="CASCADE"), nullable=False)
    model_definition_id = Column(Integer, ForeignKey("model_definitions.id", ondelete="CASCADE"), nullable=False)
    display_order = Column(Integer, default=0)


class TaskEvent(Base):
    __tablename__ = "task_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    event_type = Column(Text, nullable=False)  # dispatched/completed/timeout/manual_complete/abandoned/redispatched/updated/error
    detail = Column(Text)
    created_at = Column(DateTime, default=utcnow)
