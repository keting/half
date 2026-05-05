import type { Agent, AgentModelConfig } from '../types';

export interface DerivedStatus {
  status: 'available' | 'unavailable' | 'short_reset_pending' | 'long_reset_pending';
  label: string;
  color: string;
  canChangeStatus: boolean;
}

function pad2(value: number) {
  return String(value).padStart(2, '0');
}

function parseStoredDateTime(value: string | null | undefined) {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), hour: Number(match[4]), minute: Number(match[5]) };
}

function beijingPartsToEpoch(parts: ReturnType<typeof parseStoredDateTime>) {
  if (!parts) return Number.NaN;
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour - 8, parts.minute);
}

function getCurrentBeijingParts() {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });
  const values = Object.fromEntries(
    formatter.formatToParts(new Date()).filter((p) => p.type !== 'literal').map((p) => [p.type, Number(p.value)]),
  );
  return { year: values.year, month: values.month, day: values.day, hour: values.hour, minute: values.minute };
}

export function deriveAgentStatus(agent: Agent): DerivedStatus {
  if (!agent.is_active) {
    return { status: 'unavailable', label: '已停用', color: '#f97316', canChangeStatus: false };
  }

  // 1. Subscription expiration takes highest priority
  if (agent.subscription_expires_at) {
    const parts = parseStoredDateTime(agent.subscription_expires_at);
    const expiryEpoch = beijingPartsToEpoch(parts);
    const nowEpoch = beijingPartsToEpoch(getCurrentBeijingParts());
    if (!Number.isNaN(expiryEpoch) && expiryEpoch <= nowEpoch) {
      return { status: 'unavailable', label: '不可用', color: '#ef4444', canChangeStatus: false };
    }
  }

  const storedStatus = agent.availability_status;

  // 2. Short reset pending
  if (storedStatus === 'short_reset_pending') {
    if (agent.short_term_reset_at) {
      const parts = parseStoredDateTime(agent.short_term_reset_at);
      const resetEpoch = beijingPartsToEpoch(parts);
      const nowEpoch = beijingPartsToEpoch(getCurrentBeijingParts());
      if (!Number.isNaN(resetEpoch) && resetEpoch > nowEpoch && parts) {
        const label = `${parts.month}/${parts.day} ${pad2(parts.hour)}:${pad2(parts.minute)}可用`;
        return { status: 'short_reset_pending', label, color: '#3b82f6', canChangeStatus: true };
      }
    }
    // Reset time passed or not set — treat as available
    return { status: 'available', label: '可用', color: '#22c55e', canChangeStatus: true };
  }

  // 3. Long reset pending
  if (storedStatus === 'long_reset_pending') {
    if (agent.long_term_reset_at) {
      const parts = parseStoredDateTime(agent.long_term_reset_at);
      const resetEpoch = beijingPartsToEpoch(parts);
      const nowEpoch = beijingPartsToEpoch(getCurrentBeijingParts());
      if (!Number.isNaN(resetEpoch) && resetEpoch > nowEpoch && parts) {
        const label = `${parts.month}/${parts.day} ${pad2(parts.hour)}:${pad2(parts.minute)}可用`;
        return { status: 'long_reset_pending', label, color: '#3b82f6', canChangeStatus: true };
      }
    }
    return { status: 'available', label: '可用', color: '#22c55e', canChangeStatus: true };
  }

  // 4. Default: available
  return { status: 'available', label: '可用', color: '#22c55e', canChangeStatus: true };
}

/** @deprecated Use deriveAgentStatus instead */
export function deriveAgentAvailabilityStatus(agent: Agent): string {
  const derived = deriveAgentStatus(agent);
  if (derived.status === 'unavailable') return 'expired';
  if (derived.status === 'available') return 'online';
  return derived.status;
}

export function isSubscriptionExpiringSoon(agent: Agent): boolean {
  if (!agent.subscription_expires_at) return false;
  const parts = parseStoredDateTime(agent.subscription_expires_at);
  const expiryEpoch = beijingPartsToEpoch(parts);
  const nowEpoch = beijingPartsToEpoch(getCurrentBeijingParts());
  if (Number.isNaN(expiryEpoch) || Number.isNaN(nowEpoch)) return false;
  const diffMs = expiryEpoch - nowEpoch;
  return diffMs > 0 && diffMs < 48 * 60 * 60 * 1000;
}

export function getAgentModels(agent: Agent): AgentModelConfig[] {
  if (agent.models?.length) {
    return agent.models;
  }
  if (agent.model_name) {
    return [{ model_name: agent.model_name, capability: agent.capability }];
  }
  return [];
}

export function summarizeAgentCapabilities(agent: Agent): string {
  const models = getAgentModels(agent);
  const capabilities = Array.from(new Set(models.map((model) => model.capability).filter(Boolean) as string[]));
  if (capabilities.length > 0) {
    return capabilities.join('；');
  }
  return agent.capability || '';
}
