import { describe, expect, it } from 'vitest';
import { formatBlockedPredecessor } from './ProjectDetailPage';

describe('formatBlockedPredecessor', () => {
  it('describes blocked tasks as waiting for predecessors to complete', () => {
    expect(formatBlockedPredecessor({
      task_code: 'T2_TEST',
      task_name: '测试环境在线验证',
      expected_path: 'demo/outputs/T2_TEST/result.json',
    })).toBe('等待 T2_TEST（测试环境在线验证）完成');
  });

  it('falls back to task code for unknown predecessors', () => {
    expect(formatBlockedPredecessor({
      task_code: 'T9_UNKNOWN',
      task_name: '(未知)',
      expected_path: '',
    })).toBe('等待 T9_UNKNOWN 完成');
  });
});
