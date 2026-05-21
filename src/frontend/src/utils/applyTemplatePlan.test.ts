import { describe, expect, it, vi } from 'vitest';

import { applyTemplatePlan, filterTemplateInputs, getMissingTemplateInputs } from './applyTemplatePlan';
import type { TemplateApplyApi } from './applyTemplatePlan';

function createApi(): TemplateApplyApi {
  return {
    put: vi.fn(async () => ({})),
    post: vi.fn(async () => ({})),
  };
}

describe('applyTemplatePlan', () => {
  it('filters template inputs to declared keys and detects missing required values', () => {
    const requiredInputs = [
      { key: 'test_url', label: '测试系统 URL', required: true, sensitive: false },
      { key: 'password', label: '密码', required: true, sensitive: true },
      { key: 'report_path', label: '报告输出路径', required: false, sensitive: false },
    ];

    expect(filterTemplateInputs(requiredInputs, {
      test_url: 'https://example.test',
      password: ' secret ',
      extra: 'ignored',
    })).toEqual({
      test_url: 'https://example.test',
      password: ' secret ',
      report_path: '',
    });
    expect(getMissingTemplateInputs(requiredInputs, { test_url: 'https://example.test', password: '   ' }))
      .toEqual([requiredInputs[1]]);
  });

  it('uses required input defaults when values were not initialized', () => {
    const requiredInputs = [
      { key: 'review_prompt', label: '评审提示词', required: true, sensitive: false, default_value: '内置评审提示词' },
      { key: 'issue_url', label: 'Issue URL', required: true, sensitive: false },
    ];

    expect(filterTemplateInputs(requiredInputs, {
      issue_url: 'https://github.com/org/repo/issues/1',
    })).toEqual({
      review_prompt: '内置评审提示词',
      issue_url: 'https://github.com/org/repo/issues/1',
    });
    expect(getMissingTemplateInputs(requiredInputs, {
      issue_url: 'https://github.com/org/repo/issues/1',
    })).toEqual([]);
    expect(getMissingTemplateInputs(requiredInputs, {
      review_prompt: '',
      issue_url: 'https://github.com/org/repo/issues/1',
    })).toEqual([requiredInputs[0]]);
  });

  it('rejects an empty planning brief before any request', async () => {
    const api = createApi();

    await expect(applyTemplatePlan({
      api,
      projectId: 12,
      templateId: 3,
      planningBrief: '   ',
      slotAgentIds: { 'agent-1': 1 },
      templateMappingComplete: true,
    })).rejects.toThrow('请先填写任务介绍。');

    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects missing required template inputs before any request', async () => {
    const api = createApi();

    await expect(applyTemplatePlan({
      api,
      projectId: 12,
      templateId: 3,
      planningBrief: '完成系统测试',
      slotAgentIds: { 'agent-1': 1 },
      templateMappingComplete: true,
      requiredInputs: [
        { key: 'test_url', label: '测试系统 URL', required: true, sensitive: false },
      ],
      templateInputs: { test_url: '   ' },
    })).rejects.toThrow('请填写所有模版所需信息。');

    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('saves goal before applying the selected template', async () => {
    const calls: string[] = [];
    const api: TemplateApplyApi = {
      put: vi.fn(async () => {
        calls.push('put');
        return {};
      }),
      post: vi.fn(async () => {
        calls.push('post');
        return {};
      }),
    };

    await applyTemplatePlan({
      api,
      projectId: 12,
      templateId: 3,
      planningBrief: '完成支付回调改造',
      slotAgentIds: { 'agent-1': 1, 'agent-2': 2 },
      templateMappingComplete: true,
      requiredInputs: [
        { key: 'test_url', label: '测试系统 URL', required: true, sensitive: false },
        { key: 'login_password', label: '登录密码', required: true, sensitive: true },
      ],
      templateInputs: {
        test_url: 'https://example.test',
        login_password: 'secret',
        extra: 'ignored',
      },
    });

    expect(calls).toEqual(['put', 'post']);
    expect(api.put).toHaveBeenCalledWith('/api/projects/12', {
      goal: '完成支付回调改造',
      template_inputs: {
        test_url: 'https://example.test',
        login_password: 'secret',
      },
    });
    expect(api.post).toHaveBeenCalledWith('/api/process-templates/3/apply/12', {
      slot_agent_ids: { 'agent-1': 1, 'agent-2': 2 },
    });
  });

  it('does not submit removed issue-review branch inputs', async () => {
    const api = createApi();
    const requiredInputs = [
      { key: 'issue_url', label: 'Issue URL', required: true, sensitive: false },
      { key: 'review_prompt', label: '评审提示词', required: true, sensitive: false },
      { key: 'test_command', label: '测试命令', required: false, sensitive: false },
      { key: 'max_review_rounds', label: '最大评审轮次', required: true, sensitive: false },
    ];

    await applyTemplatePlan({
      api,
      projectId: 8,
      templateId: 5,
      planningBrief: '实现 issue',
      slotAgentIds: { 'agent-1': 1, 'agent-2': 2, 'agent-3': 3 },
      templateMappingComplete: true,
      requiredInputs,
      templateInputs: {
        issue_url: 'https://github.com/org/repo/issues/1',
        review_prompt: '严格评审',
        test_command: 'npm test',
        max_review_rounds: '3',
        base_branch: 'develop',
        work_branch_name: 'custom-work',
        pr_target_branch: 'release',
      },
    });

    expect(api.put).toHaveBeenCalledWith('/api/projects/8', {
      goal: '实现 issue',
      template_inputs: {
        issue_url: 'https://github.com/org/repo/issues/1',
        review_prompt: '严格评审',
        test_command: 'npm test',
        max_review_rounds: '3',
      },
    });
  });

  it('does not apply the template when saving goal fails', async () => {
    const api: TemplateApplyApi = {
      put: vi.fn(async () => {
        throw new Error('save failed');
      }),
      post: vi.fn(async () => ({})),
    };

    await expect(applyTemplatePlan({
      api,
      projectId: 12,
      templateId: 3,
      planningBrief: '完成支付回调改造',
      slotAgentIds: { 'agent-1': 1 },
      templateMappingComplete: true,
    })).rejects.toThrow('save failed');

    expect(api.post).not.toHaveBeenCalled();
  });
});
