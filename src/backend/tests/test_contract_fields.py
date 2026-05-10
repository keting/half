import sys
import unittest
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routers.agents import AgentCreate, AgentResponse
from routers.projects import ProjectCreate, ProjectResponse, ProjectUpdate
from routers.process_templates import ProcessTemplateCreate, ProcessTemplateResponse, ProcessTemplateUpdate
from routers.plans import PlanResponse, PlanPromptRequest, PromptResponse
from routers.tasks import TaskResponse, TaskUpdateRequest


class ContractFieldTests(unittest.TestCase):
    def test_agent_contracts_expose_capability(self):
        self.assertIn('capability', AgentCreate.model_fields)
        self.assertIn('models', AgentCreate.model_fields)
        self.assertIn('capability', AgentResponse.model_fields)
        self.assertIn('models', AgentResponse.model_fields)
        self.assertIn('short_term_reset_at', AgentCreate.model_fields)
        self.assertIn('long_term_reset_at', AgentCreate.model_fields)
        self.assertIn('short_term_reset_interval_hours', AgentCreate.model_fields)
        self.assertIn('long_term_reset_interval_days', AgentCreate.model_fields)
        self.assertIn('short_term_reset_at', AgentResponse.model_fields)
        self.assertIn('long_term_reset_at', AgentResponse.model_fields)
        self.assertIn('short_term_reset_interval_hours', AgentResponse.model_fields)
        self.assertIn('long_term_reset_interval_days', AgentResponse.model_fields)
        self.assertIn('short_term_reset_needs_confirmation', AgentResponse.model_fields)
        self.assertIn('long_term_reset_needs_confirmation', AgentResponse.model_fields)
        self.assertIn('created_by', AgentResponse.model_fields)
        self.assertIn('owner_role', AgentResponse.model_fields)
        self.assertIn('is_public', AgentResponse.model_fields)
        self.assertIn('can_edit', AgentResponse.model_fields)
        self.assertIn('is_disabled_public', AgentResponse.model_fields)

    def test_project_contracts_expose_collaboration_dir(self):
        self.assertIn('collaboration_dir', ProjectCreate.model_fields)
        self.assertIn('collaboration_dir', ProjectResponse.model_fields)
        self.assertIn('task_timeout_minutes', ProjectCreate.model_fields)
        self.assertIn('task_timeout_minutes', ProjectResponse.model_fields)
        self.assertIn('agent_assignments', ProjectCreate.model_fields)
        self.assertIn('agent_assignments', ProjectResponse.model_fields)
        self.assertIn('planning_mode', ProjectCreate.model_fields)
        self.assertIn('planning_mode', ProjectResponse.model_fields)
        self.assertIn('template_inputs', ProjectCreate.model_fields)
        self.assertIn('template_inputs', ProjectUpdate.model_fields)
        self.assertIn('template_inputs', ProjectResponse.model_fields)

    def test_process_template_contracts_expose_required_inputs(self):
        self.assertIn('required_inputs', ProcessTemplateCreate.model_fields)
        self.assertIn('required_inputs', ProcessTemplateUpdate.model_fields)
        self.assertIn('required_inputs', ProcessTemplateResponse.model_fields)

    def test_plan_contracts_expose_generation_status_fields(self):
        self.assertIn('include_usage', PlanPromptRequest.model_fields)
        self.assertIn('selected_agent_ids', PlanPromptRequest.model_fields)
        self.assertIn('selected_agent_models', PlanPromptRequest.model_fields)
        self.assertIn('plan_id', PromptResponse.model_fields)
        self.assertIn('source_path', PromptResponse.model_fields)
        self.assertIn('status', PlanResponse.model_fields)
        self.assertIn('prompt_text', PlanResponse.model_fields)
        self.assertIn('source_path', PlanResponse.model_fields)
        self.assertIn('selected_agent_ids', PlanResponse.model_fields)
        self.assertIn('selected_agent_models', PlanResponse.model_fields)

    def test_task_contracts_expose_edit_fields(self):
        self.assertIn('task_name', TaskUpdateRequest.model_fields)
        self.assertIn('description', TaskUpdateRequest.model_fields)
        self.assertIn('expected_output_path', TaskUpdateRequest.model_fields)
        self.assertIn('timeout_minutes', TaskUpdateRequest.model_fields)
        self.assertIn('task_name', TaskResponse.model_fields)
        self.assertIn('expected_output_path', TaskResponse.model_fields)
        self.assertIn('timeout_minutes', TaskResponse.model_fields)

    def test_datetime_responses_mark_naive_datetimes_as_utc(self):
        response = TaskResponse(
            id=1,
            project_id=1,
            plan_id=1,
            task_code='T1',
            task_name='Task',
            description='',
            assignee_agent_id=None,
            status='running',
            depends_on_json='[]',
            expected_output_path='out.md',
            result_file_path=None,
            usage_file_path=None,
            last_error=None,
            timeout_minutes=10,
            dispatched_at=datetime(2026, 4, 11, 8, 7, 19),
            completed_at=None,
            created_at=None,
            updated_at=None,
        )

        self.assertIn('"dispatched_at":"2026-04-11T08:07:19Z"', response.model_dump_json())


if __name__ == '__main__':
    unittest.main()
