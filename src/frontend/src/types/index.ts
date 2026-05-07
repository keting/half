export interface AgentModelConfig {
  model_name: string;
  capability: string | null;
}

export interface CurrentUser {
  id: number;
  username: string;
  role: string;
  status: string;
}

export interface AdminUser {
  id: number;
  username: string;
  role: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
  last_login_ip: string | null;
}

export interface Agent {
  id: number;
  name: string;
  slug: string;
  agent_type: string;
  model_name: string | null;
  models: AgentModelConfig[];
  capability: string | null;
  co_located: boolean;
  is_active: boolean;
  availability_status: string;
  display_order: number;
  subscription_expires_at: string | null;
  short_term_reset_at: string | null;
  short_term_reset_interval_hours: number | null;
  short_term_reset_needs_confirmation: boolean;
  long_term_reset_at: string | null;
  long_term_reset_interval_days: number | null;
  long_term_reset_mode: string;
  long_term_reset_needs_confirmation: boolean;
  created_by: number | null;
  owner_role: 'admin' | 'user' | null;
  is_public: boolean;
  can_edit: boolean;
  is_disabled_public: boolean;
}

export interface ModelDefinition {
  id: number;
  name: string;
  alias: string | null;
  capability: string | null;
}

export interface AgentTypeConfig {
  id: number;
  name: string;
  description: string | null;
  models: ModelDefinition[];
}

export interface ProjectAgentAssignment {
  id: number;
  co_located: boolean;
}

export interface Project {
  id: number;
  name: string;
  goal: string;
  git_repo_url: string;
  collaboration_dir?: string | null;
  status: string;
  created_by?: number | null;
  created_at: string;
  agent_ids?: number[];
  agent_assignments?: ProjectAgentAssignment[];
  polling_interval_min?: number | null;
  polling_interval_max?: number | null;
  polling_start_delay_minutes?: number | null;
  polling_start_delay_seconds?: number | null;
  task_timeout_minutes?: number | null;
  planning_mode?: string;
  template_inputs?: Record<string, string>;
  inactive_agent_ids?: number[];
  next_step?: string | {
    action: string;
    message: string;
  };
  task_summary?: {
    total: number;
    pending: number;
    running: number;
    completed: number;
    needs_attention: number;
    abandoned: number;
  };
}

export interface Plan {
  id: number;
  project_id: number;
  source_agent_id: number | null;
  plan_type: string;
  plan_json: string | null;
  prompt_text?: string | null;
  status: string;
  source_path?: string | null;
  include_usage?: boolean;
  selected_agent_ids: number[];
  selected_agent_models?: Record<number, string | null>;
  dispatched_at?: string | null;
  detected_at?: string | null;
  last_error?: string | null;
  is_selected: boolean;
  created_at: string;
  updated_at?: string;
}

export interface TemplateRequiredInput {
  key: string;
  label: string;
  required: boolean;
  sensitive: boolean;
}

export interface ProcessTemplate {
  id: number;
  name: string;
  description: string | null;
  prompt_source_text: string | null;
  agent_count: number;
  agent_slots: string[];
  agent_roles_description: Record<string, string>;
  required_inputs: TemplateRequiredInput[];
  template_json: string;
  created_by: number | null;
  updated_by: number | null;
  can_edit: boolean;
  created_at: string | null;
  updated_at?: string | null;
}

export interface Task {
  id: number;
  project_id: number;
  task_code: string;
  task_name: string;
  assignee_label?: string | null;
  description: string;
  assignee_agent_id: number | null;
  status: string;
  depends_on_json: string;
  expected_output_path: string;
  result_file_path: string | null;
  usage_file_path: string | null;
  last_error: string | null;
  timeout_minutes: number;
  dispatched_at: string | null;
  completed_at: string | null;
}

export interface TaskEvent {
  id: number;
  task_id: number;
  event_type: string;
  detail: string | null;
  created_at: string;
}

export interface FeishuSettings {
  webhook_url: string;
  notify_events: string[];
}
