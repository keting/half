export interface AgentModelConfig {
  model_name: string;
  capability: string | null;
}

export interface Agent {
  id: number;
  name: string;
  slug: string;
  agent_type: string;
  model_name: string | null;
  models: AgentModelConfig[];
  capability: string | null;
  machine_label: string | null;
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

export interface Project {
  id: number;
  name: string;
  goal: string;
  git_repo_url: string;
  collaboration_dir?: string | null;
  status: string;
  created_at: string;
  agent_ids?: number[];
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
