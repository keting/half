import type { Project } from '../types';
import type { TemplateRequiredInput } from '../types';

export interface TemplateApplyApi {
  put<T>(path: string, body?: unknown): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
}

export interface ApplyTemplatePlanInput {
  api: TemplateApplyApi;
  projectId: string | number | undefined;
  templateId: number | null;
  planningBrief: string;
  slotAgentIds: Record<string, number | null>;
  templateMappingComplete: boolean;
  requiredInputs?: TemplateRequiredInput[];
  templateInputs?: Record<string, string>;
}

export function filterTemplateInputs(
  requiredInputs: TemplateRequiredInput[] = [],
  templateInputs: Record<string, string> = {}
): Record<string, string> {
  return Object.fromEntries(
    requiredInputs.map((input) => [input.key, templateInputs[input.key] ?? input.default_value ?? ''])
  );
}

export function getMissingTemplateInputs(
  requiredInputs: TemplateRequiredInput[] = [],
  templateInputs: Record<string, string> = {}
): TemplateRequiredInput[] {
  return requiredInputs.filter((input) => input.required && !(templateInputs[input.key] ?? input.default_value ?? '').trim());
}

export async function applyTemplatePlan({
  api,
  projectId,
  templateId,
  planningBrief,
  slotAgentIds,
  templateMappingComplete,
  requiredInputs = [],
  templateInputs = {},
}: ApplyTemplatePlanInput): Promise<void> {
  if (!planningBrief.trim()) {
    throw new Error('请先填写任务介绍。');
  }
  if (!templateId) {
    throw new Error('请先选择一个流程模版。');
  }
  if (!templateMappingComplete) {
    throw new Error('请完成所有角色映射，且不要重复选择同一个 Agent。');
  }
  if (getMissingTemplateInputs(requiredInputs, templateInputs).length) {
    throw new Error('请填写所有模版所需信息。');
  }

  await api.put<Project>(`/api/projects/${projectId}`, {
    goal: planningBrief,
    template_inputs: filterTemplateInputs(requiredInputs, templateInputs),
  });
  await api.post(`/api/process-templates/${templateId}/apply/${projectId}`, {
    slot_agent_ids: slotAgentIds,
  });
}
