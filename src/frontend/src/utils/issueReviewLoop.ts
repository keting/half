import type { FlowState, Task } from '../types';

export const ISSUE_REVIEW_LOOP_ATTENTION_MESSAGE = '评审仍有冲突，已达到最大评审轮次，需要人工介入。';

export function hasIssueReviewLoopAttention(flowState?: FlowState | null): boolean {
  return Boolean(
    flowState?.enabled
      && (flowState.derived_phase === 'needs_attention' || flowState.phase === 'needs_attention')
  );
}

export function isIssueReviewLoopAttentionTask(task: Task, flowState?: FlowState | null): boolean {
  return task.task_code === 'TASK-005' && hasIssueReviewLoopAttention(flowState);
}
