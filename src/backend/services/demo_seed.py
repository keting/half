import json
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import (
    Agent,
    AgentTypeConfig,
    AgentTypeModelMap,
    GlobalSetting,
    ModelDefinition,
    ProcessTemplate,
    Project,
    ProjectPlan,
    Task,
    TaskEvent,
    User,
    utcnow,
)
from services.project_agents import serialize_agent_assignments

DEMO_META_KEY = "demo_project_seed_v1"
DEMO_PROJECT_NAME = "(Demo) 修复一个bug"
DEMO_TEMPLATE_NAME = "【代码】中等规模功能开发与 Bug 修复代码实施全流程"

DEMO_COLLABORATION_DIR = "demo/half-demo-collaboration"
DEMO_REPO_URL = "https://github.com/keting/half.git"

_MODEL_CAPABILITIES = {
    "gpt-5.5": (
        "优先处理高复杂度、强推理、长链路的专业工作，如大型代码库改造、跨系统问题排查、"
        "深度研究分析、复杂产品/架构决策与端到端交付；相比 GPT-5.4，它更适合作为高难度任务的主代理、"
        "复杂项目的技术总控，以及需要更强规划、判断和执行一致性的专业工作核心。"
    ),
    "gpt-5.4": (
        "优先处理跨工具专业工作，如需求到交付的多步骤流程、文档/表格/演示文稿联动、"
        "复杂分析与高质量交付；比通用编码模型更适合作为专业流程总控与强代理核心。"
    ),
    "Opus 4.7": (
        "派给最难任务：跨文档需求澄清、关键架构取舍、复杂重构、疑难排障、严格代码审查、"
        "深度论文评审；强项是长链路规划、大代码库可靠性和自纠错，不要浪费在常规实现上。"
    ),
    "Opus 4.6": (
        "适合高难度代码审查、复杂需求澄清、架构判断和跨文件改造；可作为质量把关和深度评审模型。"
    ),
    "Sonnet 4.6": (
        "默认主力模型；适合大多数生产任务，尤其是需求细化、设计展开、业务代码实现、测试补全、"
        "技术文档和知识工作；当效果接近旗舰时，优先用它以换取更好成本/速度平衡。"
    ),
}

DEMO_AGENTS = [
    {
        "name": "Claude Max",
        "slug": "claude-max",
        "agent_type": "claude-max",
        "model_name": "Opus 4.7",
        "models": ["Opus 4.7", "Sonnet 4.6"],
        "co_located": False,
        "display_order": 1,
    },
    {
        "name": "Codex Pro",
        "slug": "codex-pro",
        "agent_type": "chatgpt-pro",
        "model_name": "gpt-5.5",
        "models": ["gpt-5.5", "gpt-5.4"],
        "co_located": True,
        "display_order": 2,
    },
    {
        "name": "Copilot Pro",
        "slug": "copilot-pro",
        "agent_type": "copilot-pro",
        "model_name": "Opus 4.6",
        "models": ["Opus 4.6", "gpt-5.4", "Sonnet 4.6", "Opus 4.7"],
        "co_located": False,
        "display_order": 3,
    },
]

DEMO_AGENT_TYPE_CATALOG = [
    {
        "name": "claude-max",
        "description": "Claude Max subscription agent for deep review, architecture, and complex reasoning tasks.",
        "models": ["Opus 4.7", "Sonnet 4.6"],
    },
    {
        "name": "chatgpt-pro",
        "description": "ChatGPT Pro agent for high-complexity implementation, planning, and end-to-end delivery.",
        "models": ["gpt-5.5", "gpt-5.4"],
    },
    {
        "name": "copilot-pro",
        "description": "Copilot Pro agent for implementation support, testing, and code review workflows.",
        "models": ["Opus 4.6", "gpt-5.4", "Sonnet 4.6", "Opus 4.7"],
    },
]

LEGACY_DEFAULT_AGENT_TYPES = {"claude", "codex", "cursor", "windsurf"}

DEMO_AGENT_ROLES = {
    "agent-1": "承担代码开发、本地部署自测、修改报告编写、测试与审查意见评估迭代、文档同步及最终代码和报告推送，适合具备开发、测试协调与工程交付能力的 Agent",
    "agent-2": "依据修改报告对测试环境系统进行在线功能与回归测试，验证问题修复效果，输出测试结论，无需访问源代码，适合专业系统测试与业务验证类 Agent",
    "agent-3": "根据修改报告对代码变更进行专项审查，确保问题解决且无新问题引入，输出审查结论，适合代码质量管控与技术评审类 Agent",
}

DEMO_TASKS = [
    {
        "task_code": "T1_DEV",
        "task_name": "代码开发与本地部署验证",
        "description": "依据方案进行代码开发与测试，重新部署本地系统后执行端到端测试，编写修改报告并推送至远端",
        "assignee_slot": "agent-1",
        "assignee_slug": "codex-pro",
        "depends_on": [],
        "status": "completed",
    },
    {
        "task_code": "T2_TEST",
        "task_name": "测试环境在线验证",
        "description": "读取修改报告并对目标系统进行功能与回归测试，重点验证修复问题及关联模块，输出测试结论并同步至远端",
        "assignee_slot": "agent-2",
        "assignee_slug": "copilot-pro",
        "depends_on": ["T1_DEV"],
        "status": "pending",
    },
    {
        "task_code": "T3_REVIEW",
        "task_name": "代码变更审查",
        "description": "依据修改报告审查代码修改内容，确认问题修复效果与代码质量，避免引入新问题，输出审查结论并同步至远端",
        "assignee_slot": "agent-3",
        "assignee_slug": "claude-max",
        "depends_on": ["T1_DEV"],
        "status": "pending",
    },
    {
        "task_code": "T4_EVAL",
        "task_name": "修改意见评估与迭代",
        "description": "综合测试与审查结论评估意见合理性，确定是否迭代修改，协调沟通直至达成一致结论",
        "assignee_slot": "agent-1",
        "assignee_slug": "codex-pro",
        "depends_on": ["T2_TEST", "T3_REVIEW"],
        "status": "pending",
    },
    {
        "task_code": "T5_SYNC",
        "task_name": "文档同步与最终交付",
        "description": "同步更新需求与设计文档，推送代码及文档至远端仓库，生成并提交全流程最终修改报告",
        "assignee_slot": "agent-1",
        "assignee_slug": "codex-pro",
        "depends_on": ["T4_EVAL"],
        "status": "pending",
    },
]

DEMO_TEMPLATE_INPUTS = {
    "docPath": f"{DEMO_COLLABORATION_DIR}/bug.md",
    "test_url": "https://demo.example.test",
    "test_name": "demo",
    "test_password": "DemoPass123",
    "final_report": f"{DEMO_COLLABORATION_DIR}/final-report.md",
    "prd": f"{DEMO_COLLABORATION_DIR}/prd.md",
    "tech_spec": f"{DEMO_COLLABORATION_DIR}/tech-spec.md",
}


def _ensure_app_meta(db: Session) -> None:
    db.execute(text("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"))


def _demo_seed_already_loaded(db: Session) -> bool:
    _ensure_app_meta(db)
    return bool(db.execute(text("SELECT value FROM app_meta WHERE key = :key"), {"key": DEMO_META_KEY}).scalar())


def _mark_demo_seed_loaded(db: Session) -> None:
    _ensure_app_meta(db)
    db.execute(
        text("INSERT OR REPLACE INTO app_meta(key, value) VALUES (:key, :value)"),
        {"key": DEMO_META_KEY, "value": "done"},
    )


def _model_entries(model_names: list[str]) -> list[dict[str, str]]:
    return [
        {"model_name": model_name, "capability": _MODEL_CAPABILITIES[model_name]}
        for model_name in model_names
    ]


def _ensure_agent(db: Session, admin: User, spec: dict) -> Agent:
    agent = db.query(Agent).filter(Agent.slug == spec["slug"]).first()
    models = _model_entries(spec["models"])
    capability = "；".join(item["capability"] for item in models)
    if agent is None:
        agent = Agent(slug=spec["slug"])
        db.add(agent)

    now = utcnow()
    agent.name = spec["name"]
    agent.agent_type = spec["agent_type"]
    agent.model_name = spec["model_name"]
    agent.models_json = json.dumps(models, ensure_ascii=False)
    agent.capability = capability
    agent.co_located = spec["co_located"]
    agent.is_active = True
    agent.availability_status = "available"
    agent.subscription_expires_at = now + timedelta(days=365)
    agent.short_term_reset_at = now + timedelta(hours=5)
    agent.short_term_reset_interval_hours = 5
    agent.short_term_reset_needs_confirmation = False
    agent.long_term_reset_at = now + timedelta(days=7)
    agent.long_term_reset_interval_days = 7
    agent.long_term_reset_mode = "days"
    agent.long_term_reset_needs_confirmation = False
    agent.display_order = spec["display_order"]
    agent.created_by = admin.id
    return agent


def _ensure_agent_type_catalog(db: Session) -> None:
    max_order = db.query(AgentTypeConfig.display_order).order_by(
        AgentTypeConfig.display_order.desc(),
        AgentTypeConfig.id.desc(),
    ).first()
    next_type_order = (max_order[0] + 1) if max_order and max_order[0] is not None else 0

    for type_spec in DEMO_AGENT_TYPE_CATALOG:
        agent_type = db.query(AgentTypeConfig).filter(AgentTypeConfig.name == type_spec["name"]).first()
        if agent_type is None:
            agent_type = AgentTypeConfig(
                name=type_spec["name"],
                description=type_spec["description"],
                display_order=next_type_order,
            )
            next_type_order += 1
            db.add(agent_type)
            db.flush()
        elif not agent_type.description:
            agent_type.description = type_spec["description"]

        for model_order, model_name in enumerate(type_spec["models"]):
            model_def = db.query(ModelDefinition).filter(ModelDefinition.name == model_name).first()
            if model_def is None:
                model_def = ModelDefinition(
                    name=model_name,
                    capability=_MODEL_CAPABILITIES.get(model_name),
                )
                db.add(model_def)
                db.flush()
            elif not model_def.capability:
                model_def.capability = _MODEL_CAPABILITIES.get(model_name)

            existing_map = db.query(AgentTypeModelMap).filter(
                AgentTypeModelMap.agent_type_id == agent_type.id,
                AgentTypeModelMap.model_definition_id == model_def.id,
            ).first()
            if existing_map is None:
                db.add(AgentTypeModelMap(
                    agent_type_id=agent_type.id,
                    model_definition_id=model_def.id,
                    display_order=model_order,
                ))


def _prune_unused_legacy_default_agent_types(db: Session) -> None:
    """Keep the demo settings catalog focused without deleting user data.

    The app seeds a generic catalog before the demo project is loaded. In demo
    databases that leaves unused defaults such as cursor/windsurf alongside the
    three demo agent types. Prune only known legacy defaults, and only when no
    Agent references them.
    """
    used_type_names = {
        row[0]
        for row in db.query(Agent.agent_type).filter(Agent.agent_type.isnot(None)).distinct().all()
    }
    removable_names = LEGACY_DEFAULT_AGENT_TYPES - used_type_names
    if not removable_names:
        return

    removable_types = db.query(AgentTypeConfig).filter(AgentTypeConfig.name.in_(removable_names)).all()
    removable_type_ids = [agent_type.id for agent_type in removable_types]
    if not removable_type_ids:
        return

    db.query(AgentTypeModelMap).filter(
        AgentTypeModelMap.agent_type_id.in_(removable_type_ids)
    ).delete(synchronize_session=False)
    for agent_type in removable_types:
        db.delete(agent_type)


def _template_json() -> dict:
    return {
        "plan_name": "中等改动功能开发与 Bug 修复全流程执行模版",
        "description": "适用于已有基础版本的软件系统，依据修改方案完成中等规模功能新增或 Bug 修复，通过编码自测、在线测试、代码审查、意见迭代、文档同步实现完整交付，系统未上线无需处理历史数据",
        "agent_roles": [
            {"slot": slot, "description": description}
            for slot, description in DEMO_AGENT_ROLES.items()
        ],
        "tasks": [
            {
                "task_code": task["task_code"],
                "task_name": task["task_name"],
                "description": task["description"],
                "assignee": task["assignee_slot"],
                "depends_on": task["depends_on"],
                "expected_output": f"outputs/{task['task_code']}/result.json",
            }
            for task in DEMO_TASKS
        ],
    }


def _plan_json() -> dict:
    data = _template_json()
    data["tasks"] = [
        {
            "task_code": task["task_code"],
            "task_name": task["task_name"],
            "description": task["description"],
            "assignee": task["assignee_slug"],
            "depends_on": task["depends_on"],
            "expected_output": f"outputs/{task['task_code']}/result.json",
        }
        for task in DEMO_TASKS
    ]
    return data


def _ensure_template(db: Session, admin: User) -> ProcessTemplate:
    template = db.query(ProcessTemplate).filter(ProcessTemplate.name == DEMO_TEMPLATE_NAME).first()
    if template is None:
        template = ProcessTemplate(name=DEMO_TEMPLATE_NAME)
        db.add(template)

    template.description = "软件系统已经有一个基础版本了，根据修改方案对代码进行修改，实现新增中等程度改动量的功能或修改bug。"
    template.prompt_source_text = (
        "1、task1：agent1根据修改方案(位置：@docPath）进行编程，针对修改的内容，进行代码测试，通过后在本机重新部署系统，做在线的端到端测试，"
        "同时一定要注意不能引入新的问题。本地修改暂时不要推送到远端。测试通过后，将本次修改情况写成修改报告，输出到协作目录下，并推送到远端。\n\n"
        "2、task2：前序任务是task1，由agent2执行。从项目协作目录下读取task1的修改报告，并对部署了新代码的系统做严格的在线测试"
        "（系统部署地址：@test_url）（用户名/密码: @test_name/@test_password），并把测试结论输出到协作目录下并推送到远端。\n\n"
        "3、task3：前序任务是task1，由agent3执行。从项目协作目录下读取task1的修改报告，并对修改后的代码进行审查，确保解决了问题，同时没有引入新的问题。\n\n"
        "4、task4：前序任务是task2和task3，由agent1执行。从项目协作目录下读取task2和task3的测试结论，并对修改意见进行评估。\n\n"
        "5、task5：前序任务是task4，由agent1执行。根据修改过的代码，同步更新需求文档@prd和设计文档@tech_spec，并形成最终修改报告（@final_report）。"
    )
    template.agent_count = 3
    template.agent_slots_json = json.dumps(["agent-1", "agent-2", "agent-3"], ensure_ascii=False)
    template.agent_roles_description_json = json.dumps(DEMO_AGENT_ROLES, ensure_ascii=False)
    template.required_inputs_json = json.dumps(
        [
            {"key": "docPath", "label": "修改方案的文件路径", "required": True, "sensitive": False},
            {"key": "test_url", "label": "测试系统URL", "required": True, "sensitive": False},
            {"key": "test_name", "label": "测试系统用户名", "required": True, "sensitive": False},
            {"key": "test_password", "label": "测试系统密码", "required": True, "sensitive": False},
            {"key": "final_report", "label": "本次修改的最终报告", "required": False, "sensitive": False},
            {"key": "prd", "label": "系统需求文档", "required": False, "sensitive": False},
            {"key": "tech_spec", "label": "系统技术规格书", "required": False, "sensitive": False},
        ],
        ensure_ascii=False,
    )
    template.template_json = json.dumps(_template_json(), ensure_ascii=False)
    template.created_by = template.created_by or admin.id
    template.updated_by = admin.id
    return template


def _upsert_global_setting(db: Session, key: str, value: str, description: str) -> None:
    setting = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
    if setting is None:
        db.add(GlobalSetting(key=key, value=value, description=description))
        return
    setting.value = value
    setting.description = description


def seed_demo_project(db: Session, admin: User) -> bool:
    """Seed a browsable demo project once per database.

    Returns True when a new demo project was created. The app_meta marker lets
    users delete the demo later without it being recreated on every restart.
    """
    if _demo_seed_already_loaded(db):
        return False

    if db.query(Project).filter(Project.name == DEMO_PROJECT_NAME).first():
        _mark_demo_seed_loaded(db)
        db.commit()
        return False

    agents_by_slug = {
        spec["slug"]: _ensure_agent(db, admin, spec)
        for spec in DEMO_AGENTS
    }
    _ensure_agent_type_catalog(db)
    _prune_unused_legacy_default_agent_types(db)
    template = _ensure_template(db, admin)
    db.flush()

    codex = agents_by_slug["codex-pro"]
    copilot = agents_by_slug["copilot-pro"]
    claude = agents_by_slug["claude-max"]
    project = Project(
        name=DEMO_PROJECT_NAME,
        goal=(
            "这是一个 Demo：演示应用流程模版来修复 1 个 bug。执行 task 的 agent 不需要真的修复 bug，"
            "只需要输出任务产物，以便流程能进行下去。流程模版参数使用演示数据。"
        ),
        git_repo_url=DEMO_REPO_URL,
        collaboration_dir=DEMO_COLLABORATION_DIR,
        status="executing",
        agent_ids_json=serialize_agent_assignments([
            {"id": claude.id, "co_located": False},
            {"id": codex.id, "co_located": True},
            {"id": copilot.id, "co_located": False},
        ]),
        polling_interval_min=5,
        polling_interval_max=10,
        polling_start_delay_minutes=1,
        polling_start_delay_seconds=1,
        task_timeout_minutes=11,
        planning_mode="balanced",
        template_inputs_json=json.dumps(DEMO_TEMPLATE_INPUTS, ensure_ascii=False),
        created_by=admin.id,
    )
    db.add(project)
    db.flush()

    plan = ProjectPlan(
        project_id=project.id,
        plan_type="final",
        plan_json=json.dumps(_plan_json(), ensure_ascii=False),
        status="final",
        source_path=f"template:{template.id}",
        include_usage=False,
        selected_agent_ids_json=json.dumps([codex.id, copilot.id, claude.id]),
        selected_agent_models_json="{}",
        detected_at=utcnow(),
        is_selected=True,
    )
    db.add(plan)
    db.flush()

    task_agents = {
        "codex-pro": codex.id,
        "copilot-pro": copilot.id,
        "claude-max": claude.id,
    }
    now = utcnow()
    for task_spec in DEMO_TASKS:
        task_code = task_spec["task_code"]
        completed = task_spec["status"] == "completed"
        task = Task(
            project_id=project.id,
            plan_id=plan.id,
            task_code=task_code,
            task_name=task_spec["task_name"],
            description=task_spec["description"],
            assignee_agent_id=task_agents[task_spec["assignee_slug"]],
            status=task_spec["status"],
            depends_on_json=json.dumps(task_spec["depends_on"], ensure_ascii=False),
            expected_output_path=f"{DEMO_COLLABORATION_DIR}/outputs/{task_code}/result.json",
            result_file_path=f"{DEMO_COLLABORATION_DIR}/outputs/{task_code}/result.json" if completed else None,
            timeout_minutes=11,
            dispatched_at=now - timedelta(minutes=5) if completed else None,
            completed_at=now - timedelta(minutes=1) if completed else None,
        )
        db.add(task)
        db.flush()
        if completed:
            db.add(TaskEvent(
                task_id=task.id,
                event_type="completed",
                detail=json.dumps({
                    "result_file_path": task.result_file_path,
                    "summary": "Demo task completed. No real bug fix was required; generated task artifacts for downstream workflow consumption.",
                    "artifacts": [
                        {
                            "path": f"{DEMO_COLLABORATION_DIR}/outputs/{task_code}/report.md",
                            "type": "report",
                            "description": "Development and local deployment verification report for the demo workflow task.",
                        }
                    ],
                }, ensure_ascii=False),
            ))

    _upsert_global_setting(
        db,
        "demo_project_seed_reference",
        json.dumps({
            "project_name": DEMO_PROJECT_NAME,
            "template_name": DEMO_TEMPLATE_NAME,
            "git_repo_url": DEMO_REPO_URL,
            "collaboration_dir": DEMO_COLLABORATION_DIR,
        }, ensure_ascii=False),
        "Reference metadata for the built-in demo project seed",
    )
    _mark_demo_seed_loaded(db)
    db.commit()
    return True
