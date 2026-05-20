import { describe, expect, it } from 'vitest';

import type { FlowState, Task } from '../types';
import {
  ISSUE_REVIEW_LOOP_ATTENTION_MESSAGE,
  hasIssueReviewLoopAttention,
  isIssueReviewLoopAttentionTask,
} from './issueReviewLoop';

function flowState(overrides: Partial<FlowState> = {}): FlowState {
  return {
    enabled: true,
    exists: true,
    valid: true,
    flow_type: 'issue_code_review_loop',
    phase: 'awaiting_review',
    derived_phase: 'awaiting_review',
    current_round: 3,
    round_id: 'round-003',
    work_branch: 'issue-123',
    head_commit: 'abc123',
    max_review_rounds: 3,
    task_states: {},
    effective_task_states: {},
    reviews: {},
    decision: {},
    pr: {},
    errors: [],
    ...overrides,
  };
}

function task(taskCode: string): Task {
  return {
    id: 5,
    project_id: 1,
    task_code: taskCode,
    task_name: taskCode,
    description: '',
    assignee_agent_id: null,
    status: 'completed',
    depends_on_json: '[]',
    expected_output_path: '',
    result_file_path: null,
    usage_file_path: null,
    last_error: null,
    timeout_minutes: 10,
    dispatched_at: null,
    completed_at: null,
  };
}

describe('issue review loop UI helpers', () => {
  it('detects the manual intervention state from phase or derived phase', () => {
    expect(hasIssueReviewLoopAttention(flowState({ derived_phase: 'needs_attention' }))).toBe(true);
    expect(hasIssueReviewLoopAttention(flowState({ phase: 'needs_attention', derived_phase: 'awaiting_review' }))).toBe(true);
    expect(hasIssueReviewLoopAttention(flowState({ enabled: false, derived_phase: 'needs_attention' }))).toBe(false);
    expect(hasIssueReviewLoopAttention(flowState())).toBe(false);
  });

  it('shows the attention hint only for TASK-005', () => {
    const attentionState = flowState({
      derived_phase: 'needs_attention',
      effective_task_states: { 'TASK-005': 'completed' },
    });

    expect(ISSUE_REVIEW_LOOP_ATTENTION_MESSAGE).toContain('需要人工介入');
    expect(isIssueReviewLoopAttentionTask(task('TASK-005'), attentionState)).toBe(true);
    expect(isIssueReviewLoopAttentionTask(task('TASK-004'), attentionState)).toBe(false);
  });
});
