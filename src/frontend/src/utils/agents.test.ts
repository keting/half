import { describe, expect, it } from 'vitest';

import { deriveAgentStatus } from './agents';
import type { Agent } from '../types';

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 1,
    name: 'Agent',
    slug: 'agent',
    agent_type: 'codex',
    model_name: null,
    models: [],
    capability: null,
    co_located: false,
    is_active: true,
    availability_status: 'available',
    display_order: 0,
    subscription_expires_at: null,
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

describe('agent status helpers', () => {
  it('marks inactive agents as unavailable before derived reset status', () => {
    const status = deriveAgentStatus(makeAgent({
      is_active: false,
      availability_status: 'short_reset_pending',
      short_term_reset_at: '2099-05-01 12:00',
    }));

    expect(status.status).toBe('unavailable');
    expect(status.label).toBe('已停用');
    expect(status.canChangeStatus).toBe(false);
  });

});
