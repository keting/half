import { describe, expect, it, vi } from 'vitest';

import {
  copyText,
  getNextStepAction,
  getNextStepText,
  getPlanIdToFinalize,
} from './contracts';
import type { Agent, Project } from './types';

describe('contracts helpers', () => {
  it('uses string next_step values returned by backend', () => {
    expect(getNextStepText('Review and finalize plan')).toBe('请检查并定稿当前 Plan。');
    expect(getNextStepAction('Review and finalize plan')).toBe('');
  });

  it('prefers the selected plan and falls back to the first plan', () => {
    expect(
      getPlanIdToFinalize([
        { id: 1, is_selected: false, status: 'running' } as never,
        { id: 2, is_selected: true, status: 'completed' } as never,
      ])
    ).toBe(2);
    expect(getPlanIdToFinalize([{ id: 3, is_selected: false, status: 'completed' } as never])).toBe(3);
    expect(getPlanIdToFinalize([])).toBeNull();
  });

  it('uses clipboard api when available', async () => {
    const clipboard = { writeText: vi.fn(async () => {}) };
    await expect(copyText('prompt-body', clipboard)).resolves.toBe(true);
    expect(clipboard.writeText).toHaveBeenCalledWith('prompt-body');
  });

  it('returns false when clipboard permission is denied and legacy copy also fails', async () => {
    const originalDocument = globalThis.document;
    const execCommand = vi.fn(() => false);
    const appendChild = vi.fn();
    const removeChild = vi.fn();
    const textArea = {
      value: '',
      setAttribute: vi.fn(),
      style: {},
      focus: vi.fn(),
      select: vi.fn(),
    };
    // Minimal DOM shim for copyText fallback.
    (globalThis as any).document = {
      createElement: vi.fn(() => textArea),
      body: { appendChild, removeChild },
      execCommand,
    };

    const clipboard = { writeText: vi.fn(async () => { throw new Error('denied'); }) };
    await expect(copyText('prompt-body', clipboard)).resolves.toBe(false);
    expect(clipboard.writeText).toHaveBeenCalledWith('prompt-body');
    expect(execCommand).toHaveBeenCalledWith('copy');

    (globalThis as any).document = originalDocument;
  });

  it('exposes project collaboration_dir in the frontend project contract', () => {
    const project: Project = {
      id: 1,
      name: 'Demo',
      goal: 'Goal',
      git_repo_url: 'git@github.com:org/repo.git',
      collaboration_dir: 'tasks/shared',
      planning_mode: 'quality',
      status: 'draft',
      created_at: '2026-04-02T00:00:00Z',
      agent_ids: [1],
    };

    expect(project.collaboration_dir).toBe('tasks/shared');
    expect(project.planning_mode).toBe('quality');
  });

  it('exposes agent capability in the frontend agent contract', () => {
    const agent: Agent = {
      id: 1,
      name: 'Claude 主力',
      slug: 'claude-main',
      agent_type: 'claude',
      model_name: 'claude-sonnet-4-5',
      models: [
        { model_name: 'claude-sonnet-4-5', capability: '长文本分析、任务拆解' },
        { model_name: 'claude-opus-4-1', capability: '复杂规划' },
      ],
      capability: '长文本分析、任务拆解',
      co_located: true,
      is_active: true,
      availability_status: 'unknown',
      subscription_expires_at: null,
      short_term_reset_at: null,
      short_term_reset_interval_hours: null,
      short_term_reset_needs_confirmation: false,
      long_term_reset_at: null,
      long_term_reset_interval_days: null,
      long_term_reset_mode: 'days',
      long_term_reset_needs_confirmation: false,
      created_by: 1,
      owner_role: 'admin',
      is_public: true,
      can_edit: true,
      is_disabled_public: false,
    };

    expect(agent.capability).toContain('任务拆解');
    expect(agent.co_located).toBe(true);
  });
});
