import type { Plan, Project } from './types';

type NextStepValue = Project['next_step'] | string | null | undefined;

const NEXT_STEP_TEXT_MAP: Record<string, string> = {
  'Create project plan': '请先生成项目 Plan。',
  'Waiting for plan generation': '等待 Plan 生成完成。',
  'Review and finalize plan': '请检查并定稿当前 Plan。',
  'View execution summary': '可以查看执行总结。',
  'Waiting for running tasks to complete': '请等待运行中的任务完成。',
  'Handle tasks that need attention': '请处理需要人工关注的任务。',
  'No action available': '当前没有可执行操作。',
};

const NEXT_STEP_PREFIX_MAP: Array<[string, string]> = [
  ['Dispatch task: ', '请派发任务：'],
];

const NEXT_STEP_ACTION_MAP: Record<string, string> = {
  'Go to Plan': '前往 Plan 页面',
  'Go to Tasks': '前往任务页面',
  'View Summary': '查看总结页面',
  'Refresh': '刷新状态',
};

function translateKnownText(text: string): string {
  if (NEXT_STEP_TEXT_MAP[text]) {
    return NEXT_STEP_TEXT_MAP[text];
  }
  for (const [prefix, translatedPrefix] of NEXT_STEP_PREFIX_MAP) {
    if (text.startsWith(prefix)) {
      return `${translatedPrefix}${text.slice(prefix.length)}`;
    }
  }
  return text;
}

export function getNextStepText(nextStep: NextStepValue): string {
  if (!nextStep) {
    return '';
  }
  if (typeof nextStep === 'string') {
    return translateKnownText(nextStep);
  }
  return translateKnownText(nextStep.message);
}

export function getNextStepAction(nextStep: NextStepValue): string {
  if (!nextStep || typeof nextStep === 'string') {
    return '';
  }
  const action = nextStep.action ?? '';
  return NEXT_STEP_ACTION_MAP[action] ?? action;
}

export function getPlanIdToFinalize(plans: Plan[]): number | null {
  const selectedPlan = plans.find((plan) => plan.is_selected) ?? plans.find((plan) => plan.status === 'completed') ?? plans[0];
  return selectedPlan ? selectedPlan.id : null;
}

interface ApiClientLike {
  post<T>(path: string, body?: unknown): Promise<T>;
}

interface ClipboardLike {
  writeText(text: string): Promise<void>;
}

export async function copyText(text: string, clipboard?: ClipboardLike | null): Promise<boolean> {
  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to legacy copy handling.
    }
  }

  if (typeof document === 'undefined') {
    return false;
  }

  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', 'true');
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  textArea.style.left = '-9999px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
}

export async function copyTaskPromptAndDispatch(
  api: ApiClientLike,
  clipboard: ClipboardLike | undefined,
  taskId: number,
): Promise<string> {
  const promptResponse = await api.post<{ prompt: string }>(
    `/api/tasks/${taskId}/generate-prompt`,
    {}
  );
  await copyText(promptResponse.prompt, clipboard);
  await api.post(`/api/tasks/${taskId}/dispatch`);
  return promptResponse.prompt;
}
