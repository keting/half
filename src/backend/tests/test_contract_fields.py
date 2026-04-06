import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routers.agents import AgentCreate, AgentResponse
from routers.projects import ProjectCreate, ProjectResponse
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

    def test_project_contracts_expose_collaboration_dir(self):
        self.assertIn('collaboration_dir', ProjectCreate.model_fields)
        self.assertIn('collaboration_dir', ProjectResponse.model_fields)

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
        self.assertIn('task_name', TaskResponse.model_fields)
        self.assertIn('expected_output_path', TaskResponse.model_fields)


if __name__ == '__main__':
    unittest.main()
