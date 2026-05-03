import { describe, expect, it, vi } from 'vitest';

import {
  getUnavailableAgentSelectionMessage,
  isUnavailableAgentSelectionDisabled,
  triggerAgentCardToggle,
  triggerAgentCardToggleFromKey,
} from './ProjectNewPage';
import type { Agent } from '../types';
import { GIT_REPO_URL_ERROR, GIT_REPO_URL_REQUIRED_ERROR, validateGitRepoUrl } from '../utils/gitRepoUrl';

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    name: '默认 Agent',
    slug: 'default-agent',
    agent_type: 'claude',
    model_name: 'claude-sonnet',
    models: [{ model_name: 'claude-sonnet', capability: '分析' }],
    capability: '分析',
    co_located: false,
    is_active: true,
    availability_status: 'available',
    display_order: 0,
    subscription_expires_at: '2099-05-01 12:00',
    short_term_reset_at: null,
    short_term_reset_interval_hours: null,
    short_term_reset_needs_confirmation: false,
    long_term_reset_at: null,
    long_term_reset_interval_days: null,
    long_term_reset_mode: 'days',
    long_term_reset_needs_confirmation: false,
    created_by: 1,
    owner_role: 'user',
    is_public: false,
    can_edit: true,
    is_disabled_public: false,
    ...overrides,
  };
}

describe('ProjectNewPage unavailable agent logic', () => {
  it('marks newly selected unavailable agents as disabled', () => {
    const unavailableAgent = makeAgent({
      id: 2,
      name: '不可用 Agent',
      subscription_expires_at: '2026-04-01 00:00',
    });

    expect(isUnavailableAgentSelectionDisabled(unavailableAgent, [])).toBe(true);
  });

  it('keeps originally selected unavailable agents enabled in edit mode', () => {
    const unavailableAgent = makeAgent({
      id: 3,
      name: '已保留不可用 Agent',
      subscription_expires_at: '2026-04-01 00:00',
    });

    expect(isUnavailableAgentSelectionDisabled(unavailableAgent, [3])).toBe(false);
  });

  it('builds a chinese error message with unavailable agent names', () => {
    expect(
      getUnavailableAgentSelectionMessage([
        makeAgent({ id: 2, name: 'Agent A' }),
        makeAgent({ id: 3, name: 'Agent B' }),
      ])
    ).toBe('不可用的 Agent 无法参与项目：Agent A、Agent B');
  });

  it('does not trigger click toggle handlers for disabled cards', () => {
    const onToggle = vi.fn();

    triggerAgentCardToggle(true, onToggle);

    expect(onToggle).not.toHaveBeenCalled();
  });

  it('does not trigger keyboard toggle handlers for disabled or unrelated keys', () => {
    const onToggle = vi.fn();

    expect(triggerAgentCardToggleFromKey('Enter', true, onToggle)).toBe(false);
    expect(triggerAgentCardToggleFromKey('Escape', false, onToggle)).toBe(false);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('triggers keyboard toggle handlers for enabled enter and space keys', () => {
    const onToggle = vi.fn();

    expect(triggerAgentCardToggleFromKey('Enter', false, onToggle)).toBe(true);
    expect(triggerAgentCardToggleFromKey(' ', false, onToggle)).toBe(true);
    expect(onToggle).toHaveBeenCalledTimes(2);
  });
});

describe('ProjectNewPage Git repository URL validation', () => {
  it('allows an empty URL only when the field is optional', () => {
    expect(validateGitRepoUrl('')).toBeNull();
  });

  it('shows a distinct required error for an empty project repository URL', () => {
    expect(validateGitRepoUrl('', { required: true })).toBe(GIT_REPO_URL_REQUIRED_ERROR);
    expect(validateGitRepoUrl('   ', { required: true })).toBe(GIT_REPO_URL_REQUIRED_ERROR);
  });

  it('keeps format errors distinct from the required error', () => {
    expect(validateGitRepoUrl('www.baidu.com', { required: true })).toBe(GIT_REPO_URL_ERROR);
  });

  it.each([
    'https://github.com/org/repo',
    'https://github.com/org/repo.git',
    'https://gitlab.com/group/subgroup/repo',
    'https://gitlab.com/group/repo.git',
    'https://gitlab.com/group/subgroup/repo.git',
    'https://gitee.com/org/repo',
    'https://gitee.com/org/repo.git',
    'https://git.example.com/team/repo.git',
    'https://fcc.com/team/repo.git',
    'https://fdic.gov/team/repo.git',
    'https://git.fcompany.com/team/repo.git',
    'git@github.com:org/repo.git',
    'git@gitlab.com:group/repo.git',
    'git@gitlab.com:group/subgroup/repo.git',
    'ssh://git@github.com/org/repo.git',
    'ssh://git@github.com:22/org/repo.git',
    'ssh://git@git.example.com:2222/team/repo.git',
    'ssh://gitea@git.example.com/team/repo.git',
    'ssh://repo@git.example.com/team/repo.git',
  ])('accepts Git repository URL %s', (url) => {
    expect(validateGitRepoUrl(url)).toBeNull();
  });

  it.each([
    'www.baidu.com',
    'https://www.baidu.com',
    'https://notgithub.com/test/repo',
    'https://github.com/org',
    'https://github.com/org/repo/foo',
    'https://github.com/org/repo/graphs/contributors',
    'https://github.com/org/repo.git/graphs',
    'https://github.com/org/repo/issues',
    'https://github.com/org/repo/tree/main',
    'https://github.com/org/repo/pull/1',
    'https://gitlab.com/group/repo/-/tree/main',
    'https://gitlab.com/group/repo/graphs/contributors',
    'https://gitee.com/org/repo/foo',
    'git@github.com:org/repo/foo.git',
    'https://github.com/org/repo.git?tab=readme',
    'https://token@github.com/org/repo.git',
    'https://user:pass@git.example.com/team/repo.git',
    'https://bad host/org/repo.git',
    'https://bad_host.example.com/org/repo.git',
    'https://-bad.example.com/org/repo.git',
    'https://bad-.example.com/org/repo.git',
    'https://bad..example.com/org/repo.git',
    'https://127.1/org/repo.git',
    'https://10.1/org/repo.git',
    'https://172.16.1/org/repo.git',
    'https://192.168.1/org/repo.git',
    'https://169.254.1/org/repo.git',
    'https://2130706433/org/repo.git',
    'https://0x7f000001/org/repo.git',
    'https://012.1/org/repo.git',
    'https://0xa9fea9fe/org/repo.git',
    'http://github.com/org/repo.git',
    'file:///tmp/repo',
    'ext::ssh -oProxyCommand=calc example.com/repo.git',
    '-uhttps://github.com/org/repo.git',
    'ssh://git@[::1]/org/repo.git',
    'ssh://git@[fe80::1]/org/repo.git',
    'ssh://git@[fd12:3456::1]/org/repo.git',
    'ssh://git@[::ffff:127.0.0.1]/org/repo.git',
    'ssh://git@[::ffff:10.0.0.1]/org/repo.git',
    'ssh://git@localhost/org/repo.git',
    'ssh://git@127.0.0.1/org/repo.git',
    'ssh://git@127.1/org/repo.git',
    'ssh://git@169.254.169.254/org/repo.git',
    'ssh://git@bad_host.example.com/org/repo.git',
    'ssh://-bad@git.example.com/org/repo.git',
    'ssh://git:secret@git.example.com/org/repo.git',
    'ssh://git.example.com/org/repo.git',
  ])('rejects non-clone or unsafe Git repository URL %s', (url) => {
    expect(validateGitRepoUrl(url)).not.toBeNull();
  });
});
