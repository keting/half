import React, { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { isAdminUser } from '../auth';
import { Agent, AgentModelConfig, AgentTypeConfig, ModelDefinition } from '../types';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';
// StatusBadge is rendered inline in agent cards for the dropdown interaction
import ModelBadge from '../components/ModelBadge';
import CountdownChip from '../components/CountdownChip';
import { deriveAgentStatus, isSubscriptionExpiringSoon, getAgentModels } from '../utils/agents';

interface AgentModelForm {
  model_name: string;
  custom_model_name: string;
  capability: string;
}

interface AgentForm {
  name: string;
  agent_type: string;
  custom_agent_type: string;
  models: AgentModelForm[];
  co_located: boolean;
  is_active: boolean;
  subscription_expires_at: string;
  short_term_reset_at: string;
  short_term_reset_timezone: string;
  short_term_reset_interval_hours: string;
  long_term_reset_at: string;
  long_term_reset_timezone: string;
  long_term_reset_interval_days: string;
  long_term_reset_mode: string;
}

// Agent types and models are fetched from /api/agent-settings/types

const TIMEZONE_OPTIONS = [
  { value: 'CST', label: 'CST (UTC+8)', offsetMinutes: 8 * 60 },
  { value: 'UTC', label: 'UTC (UTC+0)', offsetMinutes: 0 },
  { value: 'GMT', label: 'GMT (UTC+0)', offsetMinutes: 0 },
  { value: 'EST', label: 'EST (UTC-5)', offsetMinutes: -5 * 60 },
  { value: 'EDT', label: 'EDT (UTC-4)', offsetMinutes: -4 * 60 },
  { value: 'CET', label: 'CET (UTC+1)', offsetMinutes: 60 },
  { value: 'CEST', label: 'CEST (UTC+2)', offsetMinutes: 120 },
  { value: 'PST', label: 'PST (UTC-8)', offsetMinutes: -8 * 60 },
  { value: 'PDT', label: 'PDT (UTC-7)', offsetMinutes: -7 * 60 },
];

function createEmptyModelForm(): AgentModelForm {
  return { model_name: '', custom_model_name: '', capability: '' };
}

function createEmptyForm(): AgentForm {
  return {
    name: '',
    agent_type: '',
    custom_agent_type: '',
    models: [createEmptyModelForm()],
    co_located: false,
    is_active: true,
    subscription_expires_at: '',
    short_term_reset_at: '',
    short_term_reset_timezone: 'CST',
    short_term_reset_interval_hours: '',
    long_term_reset_at: '',
    long_term_reset_timezone: 'CST',
    long_term_reset_interval_days: '',
    long_term_reset_mode: 'days',
  };
}

function normalizeAgentModelsForForm(agent: Agent, modelOptions: string[]): AgentModelForm[] {
  const agentModels = getAgentModels(agent);
  if (agentModels.length === 0) {
    return [createEmptyModelForm()];
  }
  return agentModels.map((model) => ({
    model_name: modelOptions.includes(model.model_name) ? model.model_name : '__custom__',
    custom_model_name: modelOptions.includes(model.model_name) ? '' : model.model_name,
    capability: model.capability || '',
  }));
}

function pad2(value: number) {
  return String(value).padStart(2, '0');
}

function formatForDateTimeLocal(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function parseDateTimeLocal(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), hour: Number(match[4]), minute: Number(match[5]) };
}

function parseStoredDateTime(value: string | null | undefined) {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), hour: Number(match[4]), minute: Number(match[5]) };
}

function formatPartsForDateTimeLocal(parts: ReturnType<typeof parseDateTimeLocal>) {
  if (!parts) return '';
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}T${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

function formatPartsForPreview(parts: ReturnType<typeof parseDateTimeLocal>) {
  if (!parts) return '未设置';
  return `${parts.year}/${parts.month}/${parts.day} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

function convertToBeijingLocalValue(localValue: string, timezoneCode: string) {
  if (!localValue) return null;
  const parsed = parseDateTimeLocal(localValue);
  if (!parsed) return null;
  const timezone = TIMEZONE_OPTIONS.find((o) => o.value === timezoneCode) || TIMEZONE_OPTIONS[0];
  const totalMinutes = (parsed.hour * 60 + parsed.minute) - timezone.offsetMinutes + (8 * 60);
  const shiftedDate = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day, 0, 0));
  shiftedDate.setUTCMinutes(totalMinutes);
  return [shiftedDate.getUTCFullYear(), pad2(shiftedDate.getUTCMonth() + 1), pad2(shiftedDate.getUTCDate())].join('-') + `T${pad2(shiftedDate.getUTCHours())}:${pad2(shiftedDate.getUTCMinutes())}`;
}

function formatBeijingPreview(localValue: string, timezoneCode: string) {
  return formatPartsForPreview(parseStoredDateTime(convertToBeijingLocalValue(localValue, timezoneCode)));
}

function formatBeijingStoredForInput(value: string | null | undefined) {
  return formatPartsForDateTimeLocal(parseStoredDateTime(value));
}

function beijingPartsToEpoch(parts: ReturnType<typeof parseDateTimeLocal>) {
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

function formatCountdown(resetTime: string | null | undefined) {
  if (!resetTime) return { display: '-', tooltip: '', diffMs: Infinity };
  const parts = parseStoredDateTime(resetTime);
  const resetEpoch = beijingPartsToEpoch(parts);
  const nowEpoch = beijingPartsToEpoch(getCurrentBeijingParts());
  if (Number.isNaN(resetEpoch) || Number.isNaN(nowEpoch)) return { display: '-', tooltip: '', diffMs: Infinity };
  const diffMs = resetEpoch - nowEpoch;
  const tooltip = parts ? `${parts.year}/${parts.month}/${parts.day} ${pad2(parts.hour)}:${pad2(parts.minute)}` : '';
  if (diffMs < 0) return { display: '已过期', tooltip, diffMs };
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const days = Math.floor(diffMinutes / (24 * 60));
  const hours = Math.floor((diffMinutes % (24 * 60)) / 60);
  const minutes = diffMinutes % 60;
  let display = '';
  if (days > 0) display = `${days}d ${hours}h ${minutes}m`;
  else if (hours > 0) display = `${hours}h ${minutes}m`;
  else display = `${minutes}m`;
  return { display, tooltip, diffMs };
}

function formatBeijingDisplay(value: string | null | undefined) {
  const parts = parseStoredDateTime(value);
  if (!parts) return null;
  return `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

export default function AgentsPage() {
  const navigate = useNavigate();
  const isAdmin = isAdminUser();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<AgentForm>(createEmptyForm);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [actionAgentId, setActionAgentId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [statusDropdownAgentId, setStatusDropdownAgentId] = useState<number | null>(null);
  const statusDropdownRef = useRef<HTMLDivElement>(null);
  const [agentTypeConfigs, setAgentTypeConfigs] = useState<AgentTypeConfig[]>([]);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);

  useEffect(() => {
    if (!statusDropdownAgentId) return;
    function handleClickOutside(e: MouseEvent) {
      if (statusDropdownRef.current && !statusDropdownRef.current.contains(e.target as Node)) {
        setStatusDropdownAgentId(null);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [statusDropdownAgentId]);

  const agentTypeNames = useMemo(() => agentTypeConfigs.map((t) => t.name), [agentTypeConfigs]);
  const effectiveAgentType = form.agent_type === '__custom__' ? form.custom_agent_type.trim() : form.agent_type;
  const currentTypeConfig = useMemo(() => agentTypeConfigs.find((t) => t.name === effectiveAgentType), [agentTypeConfigs, effectiveAgentType]);
  const modelOptions = useMemo(() => currentTypeConfig?.models || [], [currentTypeConfig]);
  const modelOptionNames = useMemo(() => modelOptions.map((m) => m.name), [modelOptions]);

  // Look up capability from model definition for a given model name
  function getModelCapability(modelName: string): string {
    for (const typeConfig of agentTypeConfigs) {
      for (const model of typeConfig.models) {
        if (model.name === modelName || model.alias === modelName) {
          return model.capability || '';
        }
      }
    }
    return '';
  }

  const resolvedFormModels = form.models
    .map((model) => {
      const name = model.model_name.trim();
      return { model_name: name, capability: getModelCapability(name) || model.capability.trim() };
    })
    .filter((model) => model.model_name);
  const resolvedCapabilitySummary = Array.from(new Set(resolvedFormModels.map((model) => model.capability).filter(Boolean))).join('；');
  const canSubmitModels = resolvedFormModels.length > 0;

  const fetchAgents = useCallback(() => {
    api.get<Agent[]>('/api/agents').then(setAgents).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const fetchTypeConfigs = useCallback(() => {
    api.get<AgentTypeConfig[]>('/api/agents/config/types').then(setAgentTypeConfigs).catch(() => {});
  }, []);

  useEffect(() => { fetchAgents(); fetchTypeConfigs(); }, [fetchAgents, fetchTypeConfigs]);

  useEffect(() => {
    const ct = window.setInterval(() => setNowTick(Date.now()), 30_000);
    const rt = window.setInterval(() => fetchAgents(), 60_000);
    return () => { window.clearInterval(ct); window.clearInterval(rt); };
  }, [fetchAgents]);

  function handleAdd() { setForm(createEmptyForm()); setEditingId(null); setShowForm(true); setError(''); }

  function handleEdit(agent: Agent) {
    if (agent.can_edit === false) return;
    const knownType = agentTypeNames.includes(agent.agent_type);
    const typeConfig = agentTypeConfigs.find((t) => t.name === agent.agent_type);
    const knownModels = typeConfig?.models.map((m) => m.name) || [];
    setForm({
      name: agent.name,
      agent_type: knownType ? agent.agent_type : '__custom__',
      custom_agent_type: knownType ? '' : agent.agent_type,
      models: normalizeAgentModelsForForm(agent, knownModels),
      co_located: Boolean(agent.co_located),
      is_active: Boolean(agent.is_active),
      subscription_expires_at: formatForDateTimeLocal(agent.subscription_expires_at),
      short_term_reset_at: formatBeijingStoredForInput(agent.short_term_reset_at),
      short_term_reset_timezone: 'CST',
      short_term_reset_interval_hours: agent.short_term_reset_interval_hours != null ? String(agent.short_term_reset_interval_hours) : '',
      long_term_reset_at: formatBeijingStoredForInput(agent.long_term_reset_at),
      long_term_reset_timezone: 'CST',
      long_term_reset_interval_days: agent.long_term_reset_interval_days != null ? String(agent.long_term_reset_interval_days) : '',
      long_term_reset_mode: agent.long_term_reset_mode || 'days',
    });
    setEditingId(agent.id);
    setShowForm(true);
    setError('');
  }

  function handleCancel() { setShowForm(false); setEditingId(null); setError(''); }
  function updateField(field: keyof AgentForm, value: string | boolean) { setForm((prev) => ({ ...prev, [field]: value })); }
  function updateModelField(index: number, field: keyof AgentModelForm, value: string) {
    setForm((prev) => ({
      ...prev,
      models: prev.models.map((model, modelIndex) => modelIndex === index ? { ...model, [field]: value } : model),
    }));
  }
  function addModelRow() {
    setForm((prev) => ({ ...prev, models: [...prev.models, createEmptyModelForm()] }));
  }
  function removeModelRow(index: number) {
    setForm((prev) => ({
      ...prev,
      models: prev.models.length === 1 ? [createEmptyModelForm()] : prev.models.filter((_, modelIndex) => modelIndex !== index),
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const payload = {
        name: form.name.trim(),
        agent_type: effectiveAgentType,
        model_name: resolvedFormModels[0]?.model_name || null,
        capability: resolvedCapabilitySummary || null,
        co_located: form.co_located,
        is_active: form.is_active,
        models: resolvedFormModels.map((model) => ({
          model_name: model.model_name,
          capability: model.capability,
        })),
        subscription_expires_at: form.subscription_expires_at || null,
        short_term_reset_at: convertToBeijingLocalValue(form.short_term_reset_at, form.short_term_reset_timezone),
        short_term_reset_interval_hours: form.short_term_reset_interval_hours.trim() ? Number(form.short_term_reset_interval_hours) : null,
        long_term_reset_at: convertToBeijingLocalValue(form.long_term_reset_at, form.long_term_reset_timezone),
        long_term_reset_interval_days: form.long_term_reset_mode === 'days' && form.long_term_reset_interval_days.trim() ? Number(form.long_term_reset_interval_days) : null,
        long_term_reset_mode: form.long_term_reset_mode,
      };
      if (editingId) await api.put(`/api/agents/${editingId}`, payload);
      else await api.post('/api/agents', payload);
      api.invalidate('/api/agents');
      setShowForm(false);
      setEditingId(null);
      fetchAgents();
    } catch (err) { setError(`保存失败：${err}`); }
    finally { setSaving(false); }
  }

  async function handleDelete(agent: Agent) {
    if (agent.can_edit === false) return;
    if (!confirm(`确认删除 "${agent.name}" 吗？`)) return;
    setDeletingId(agent.id); setError('');
    try { await api.delete(`/api/agents/${agent.id}`); api.invalidate('/api/agents'); fetchAgents(); }
    catch (err) { setError(`删除失败：${err}`); }
    finally { setDeletingId(null); }
  }

  async function handleActiveChange(agent: Agent, nextActive: boolean) {
    if (agent.can_edit === false) return;
    if (!nextActive && !confirm(`确认停用 "${agent.name}" 吗？停用后引用它的项目必须先移除该引用，才能继续编辑或生成新计划。`)) return;
    setActionAgentId(agent.id);
    setError('');
    try {
      const updated = await api.put<Agent>(`/api/agents/${agent.id}`, { is_active: nextActive });
      api.invalidate('/api/agents');
      setAgents((current) => current.map((item) => item.id === agent.id ? updated : item));
    } catch (err) {
      setError(`${nextActive ? '启用' : '停用'}失败：${err}`);
    } finally {
      setActionAgentId(null);
    }
  }

  async function handleResetAction(agentId: number, mode: 'short' | 'long') {
    const agent = agents.find((item) => item.id === agentId);
    if (agent?.can_edit === false) return;
    setActionAgentId(agentId); setError('');
    try {
      const updated = await api.post<Agent>(`/api/agents/${agentId}/${mode === 'short' ? 'short-term-reset' : 'long-term-reset'}/reset`);
      setAgents((prev) => prev.map((a) => a.id === agentId ? updated : a));
    } catch (err) { setError(`${mode === 'short' ? '短期' : '长期'}重置失败：${err}`); }
    finally { setActionAgentId(null); }
  }

  async function handleConfirmAction(agentId: number, mode: 'short' | 'long') {
    const agent = agents.find((item) => item.id === agentId);
    if (agent?.can_edit === false) return;
    setActionAgentId(agentId); setError('');
    try {
      const updated = await api.post<Agent>(`/api/agents/${agentId}/${mode === 'short' ? 'short-term-reset' : 'long-term-reset'}/confirm`);
      setAgents((prev) => prev.map((a) => a.id === agentId ? updated : a));
    } catch (err) { setError(`确认失败：${err}`); }
    finally { setActionAgentId(null); }
  }

  async function handleStatusChange(agentId: number, newStatus: string) {
    const agent = agents.find((item) => item.id === agentId);
    if (agent?.can_edit === false) return;
    setStatusDropdownAgentId(null);
    setError('');
    try {
      const updated = await api.patch<Agent>(`/api/agents/${agentId}/status`, { availability_status: newStatus });
      setAgents((prev) => prev.map((a) => a.id === agentId ? updated : a));
    } catch (err) {
      setError(`状态更新失败：${err}`);
    }
  }

  const sortedAgents = useMemo(() => {
    return [...agents].sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0));
  }, [agents]);

  // Compute the auto-sorted order (by status group, then reset time)
  const autoSortedIds = useMemo(() => {
    const statusGroupOrder = (agent: Agent): number => {
      const s = deriveAgentStatus(agent).status;
      if (s === 'available') return 0;
      if (s === 'short_reset_pending' || s === 'long_reset_pending') return 1;
      return 2; // unavailable
    };
    // For pending group: use the reset time matching the pending status
    const getPendingResetEpoch = (agent: Agent): number => {
      const s = deriveAgentStatus(agent).status;
      if (s === 'short_reset_pending' && agent.short_term_reset_at) {
        const ep = beijingPartsToEpoch(parseStoredDateTime(agent.short_term_reset_at));
        if (!Number.isNaN(ep)) return ep;
      }
      if (s === 'long_reset_pending' && agent.long_term_reset_at) {
        const ep = beijingPartsToEpoch(parseStoredDateTime(agent.long_term_reset_at));
        if (!Number.isNaN(ep)) return ep;
      }
      return Infinity;
    };
    // For available group: use the earliest of short/long reset times
    const getNearestResetEpoch = (agent: Agent): number => {
      let earliest = Infinity;
      if (agent.short_term_reset_at) {
        const ep = beijingPartsToEpoch(parseStoredDateTime(agent.short_term_reset_at));
        if (!Number.isNaN(ep) && ep < earliest) earliest = ep;
      }
      if (agent.long_term_reset_at) {
        const ep = beijingPartsToEpoch(parseStoredDateTime(agent.long_term_reset_at));
        if (!Number.isNaN(ep) && ep < earliest) earliest = ep;
      }
      return earliest;
    };
    return [...agents].sort((a, b) => {
      const groupDiff = statusGroupOrder(a) - statusGroupOrder(b);
      if (groupDiff !== 0) return groupDiff;
      const group = statusGroupOrder(a);
      if (group === 0) {
        const epochDiff = getNearestResetEpoch(a) - getNearestResetEpoch(b);
        if (epochDiff !== 0) return epochDiff;
      }
      if (group === 1) {
        const epochDiff = getPendingResetEpoch(a) - getPendingResetEpoch(b);
        if (epochDiff !== 0) return epochDiff;
      }
      return a.id - b.id;
    }).map((a) => a.id);
  }, [agents, nowTick]);

  const isManuallyOrdered = useMemo(() => {
    const editableIds = sortedAgents.filter((agent) => agent.can_edit !== false).map((a) => a.id);
    if (editableIds.length <= 1) return false;
    const autoEditableIds = autoSortedIds.filter((id) => agents.find((agent) => agent.id === id)?.can_edit !== false);
    return editableIds.some((id, i) => id !== autoEditableIds[i]);
  }, [sortedAgents, autoSortedIds, agents]);

  // Build a map of agent_type -> description from settings
  const typeDescriptionMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const t of agentTypeConfigs) {
      if (t.description) map[t.name] = t.description;
    }
    return map;
  }, [agentTypeConfigs]);

  // Determine which (agentId, modelName) pairs should show capability:
  // only the first occurrence of each model_name in auto-sort order
  const modelsWithCapability = useMemo(() => {
    const seen = new Set<string>();
    const result = new Set<string>();
    for (const agentId of autoSortedIds) {
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) continue;
      for (const model of getAgentModels(agent)) {
        if (!seen.has(model.model_name)) {
          seen.add(model.model_name);
          result.add(`${agentId}:${model.model_name}`);
        }
      }
    }
    return result;
  }, [autoSortedIds, agents]);

  async function handleAutoSort() {
    const editableAutoSortedIds = autoSortedIds.filter((id) => agents.find((agent) => agent.id === id)?.can_edit !== false);
    const updatedEditable = editableAutoSortedIds.map((id, i) => {
      const agent = agents.find((a) => a.id === id)!;
      return { ...agent, display_order: i };
    });
    setAgents((current) => current.map((agent) => updatedEditable.find((item) => item.id === agent.id) || agent));
    try {
      const result = await api.put<Agent[]>('/api/agents/reorder', { agent_ids: editableAutoSortedIds });
      setAgents(result);
    } catch {
      fetchAgents();
    }
  }

  async function handleReorder(fromId: number, toId: number) {
    if (fromId === toId) return;
    const fromAgent = agents.find((agent) => agent.id === fromId);
    const toAgent = agents.find((agent) => agent.id === toId);
    if (fromAgent?.can_edit === false || toAgent?.can_edit === false) return;
    const ordered = [...sortedAgents];
    const fromIndex = ordered.findIndex((a) => a.id === fromId);
    const toIndex = ordered.findIndex((a) => a.id === toId);
    if (fromIndex === -1 || toIndex === -1) return;
    const [moved] = ordered.splice(fromIndex, 1);
    ordered.splice(toIndex, 0, moved);
    // Optimistic update
    const updated = ordered.map((a, i) => ({ ...a, display_order: i }));
    setAgents(updated);
    try {
      const result = await api.put<Agent[]>('/api/agents/reorder', { agent_ids: updated.filter((agent) => agent.can_edit !== false).map((a) => a.id) });
      setAgents(result);
    } catch {
      fetchAgents();
    }
  }

  if (loading) return <div className="page-loading">正在加载智能体...</div>;

  // --- Form rendering ---
  function renderForm() {
    return (
      <div className="agent-form-overlay">
        <div className="agent-form-container">
          <div className="agent-form-header">
            <h2>{editingId ? '编辑智能体' : '新增智能体'}</h2>
            <button className="btn btn-ghost btn-sm" onClick={handleCancel}>关闭</button>
          </div>
          <form className="agent-form" onSubmit={handleSubmit}>
            <SectionCard title="基本信息">
              <div className="form-row">
                <div className="form-group">
                  <label>名称</label>
                  <input type="text" value={form.name} onChange={(e) => updateField('name', e.target.value)} required placeholder="例如：Claude 主力" />
                </div>
                <div className="form-group">
                  <label>订阅到期时间</label>
                  <input type="datetime-local" value={form.subscription_expires_at} onChange={(e) => updateField('subscription_expires_at', e.target.value)} />
                </div>
              </div>
              <label className="checkbox-field" title="勾选则表示该agent所在的机器与项目部署的机器是同一台">
                <input
                  type="checkbox"
                  checked={form.co_located}
                  onChange={(e) => updateField('co_located', e.target.checked)}
                />
                <span>同服务器</span>
              </label>
              <label className="checkbox-field" title="取消勾选会停用该 Agent；引用它的项目必须先移除该引用，才能继续编辑或生成新计划">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => updateField('is_active', e.target.checked)}
                />
                <span>启用 Agent</span>
              </label>
            </SectionCard>

            <SectionCard title="模型与能力">
              <div className="form-row">
                <div className="form-group">
                  <label>Agent 类型</label>
                  <select
                    value={form.agent_type}
                    onChange={(e) => {
                      updateField('agent_type', e.target.value);
                      setForm((prev) => ({ ...prev, agent_type: e.target.value, models: prev.models.map(() => createEmptyModelForm()) }));
                    }}
                  >
                    <option value="">请选择</option>
                    {agentTypeNames.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
              </div>
              <div className="model-capability-list">
                {form.models.map((model, index) => (
                  <div className="model-capability-item" key={index}>
                    <div className="form-row">
                      <div className="form-group">
                        <label>{`模型 ${index + 1}`}</label>
                        <select value={model.model_name} onChange={(e) => updateModelField(index, 'model_name', e.target.value)}>
                          <option value="">请选择模型</option>
                          {modelOptions.map((option) => <option key={option.id} value={option.name}>{option.name}{option.alias ? ` (${option.alias})` : ''}</option>)}
                        </select>
                      </div>
                      <div className="form-group">
                        <label>能力描述 <span className="helper-text">（在智能体设置中修改）</span></label>
                        <textarea
                          value={getModelCapability(model.model_name.trim()) || model.capability}
                          readOnly
                          rows={2}
                          className="textarea-readonly"
                          placeholder="请在智能体设置中配置模型能力描述"
                        />
                      </div>
                    </div>
                    <div className="model-capability-actions">
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => removeModelRow(index)}>
                        删除该模型
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={addModelRow}>
                新增模型
              </button>
            </SectionCard>

            <SectionCard title="短期重置策略" description="小时级或短窗口额度恢复周期">
              <div className="form-row">
                <div className="form-group">
                  <label>下次重置时间</label>
                  <input type="datetime-local" value={form.short_term_reset_at} onChange={(e) => updateField('short_term_reset_at', e.target.value)} />
                  <select className="tz-select" value={form.short_term_reset_timezone} onChange={(e) => updateField('short_term_reset_timezone', e.target.value)}>
                    {TIMEZONE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <div className="helper-text">北京时间：{formatBeijingPreview(form.short_term_reset_at, form.short_term_reset_timezone)}</div>
                </div>
                <div className="form-group">
                  <label>重置间隔（小时）</label>
                  <input type="number" min="1" step="1" value={form.short_term_reset_interval_hours} onChange={(e) => updateField('short_term_reset_interval_hours', e.target.value)} placeholder="例如：5" />
                </div>
              </div>
            </SectionCard>

            <SectionCard title="长期重置策略" description="日级、周级、月级或长窗口额度恢复周期">
              <div className="form-row">
                <div className="form-group">
                  <label>下次重置时间</label>
                  <input type="datetime-local" value={form.long_term_reset_at} onChange={(e) => updateField('long_term_reset_at', e.target.value)} />
                  <select className="tz-select" value={form.long_term_reset_timezone} onChange={(e) => updateField('long_term_reset_timezone', e.target.value)}>
                    {TIMEZONE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <div className="helper-text">北京时间：{formatBeijingPreview(form.long_term_reset_at, form.long_term_reset_timezone)}</div>
                </div>
                <div className="form-group">
                  <label>重置间隔模式</label>
                  <select value={form.long_term_reset_mode} onChange={(e) => updateField('long_term_reset_mode', e.target.value)}>
                    <option value="days">按天</option>
                    <option value="monthly">{(() => {
                      const bj = convertToBeijingLocalValue(form.long_term_reset_at, form.long_term_reset_timezone);
                      const parts = bj ? parseDateTimeLocal(bj) : null;
                      return parts ? `每月${parts.day}日 ${pad2(parts.hour)}:${pad2(parts.minute)}` : '每月（请先设置下次重置时间）';
                    })()}</option>
                  </select>
                </div>
                {form.long_term_reset_mode === 'days' && (
                  <div className="form-group">
                    <label>重置间隔（天）</label>
                    <input type="number" min="1" step="1" value={form.long_term_reset_interval_days} onChange={(e) => updateField('long_term_reset_interval_days', e.target.value)} placeholder="例如：7" />
                  </div>
                )}
              </div>
            </SectionCard>

            {error && <div className="error-message">{error}</div>}

            <div className="agent-form-footer">
              <button type="button" className="btn btn-ghost" onClick={handleCancel}>取消</button>
              <button type="submit" className="btn btn-primary" disabled={saving || !form.name.trim() || !effectiveAgentType || !canSubmitModels}>
                {saving ? '保存中...' : editingId ? '更新' : '创建'}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader title="智能体" description="管理可参与项目执行的Coding Agents">
        {isManuallyOrdered && (
          <button
            className="btn btn-auto-sort"
            onClick={handleAutoSort}
            title="恢复系统默认排序：按状态分组（可用→重置后可用→不可用），重置后可用组内按重置时间从近到远排列"
          >
            自动排序
          </button>
        )}
        <button className="btn btn-primary" onClick={handleAdd}>新增智能体</button>
        {isAdmin && <button className="btn btn-secondary" onClick={() => navigate('/agents/settings')}>设置</button>}
      </PageHeader>

      {error && !showForm && <div className="error-message">{error}</div>}
      {showForm && renderForm()}

      <div className="agent-card-list">
        {sortedAgents.map((agent) => {
          const shortTerm = formatCountdown(agent.short_term_reset_at);
          const longTerm = formatCountdown(agent.long_term_reset_at);
          const derivedStatus = deriveAgentStatus(agent);
          const canEditAgent = agent.can_edit !== false;
          const readonlyTitle = canEditAgent ? undefined : '公共 Agent 仅创建者可维护';
          const showShortActions = Boolean(canEditAgent && agent.short_term_reset_at && agent.short_term_reset_interval_hours && agent.short_term_reset_needs_confirmation);
          const showLongActions = Boolean(canEditAgent && agent.long_term_reset_at && (agent.long_term_reset_interval_days || agent.long_term_reset_mode === 'monthly') && agent.long_term_reset_needs_confirmation);

          let shortColor: string | undefined;
          if (shortTerm.display !== '-' && shortTerm.diffMs >= 0 && shortTerm.diffMs < 3600_000) shortColor = '#ef4444';

          let longColor: string | undefined;
          if (longTerm.display !== '-' && longTerm.diffMs >= 0) {
            if (longTerm.diffMs < 86400_000) longColor = '#ef4444';
            else if (longTerm.diffMs < 172800_000) longColor = '#e89a1d';
          }

          const expiryDisplay = formatBeijingDisplay(agent.subscription_expires_at);
          const expiringSoon = isSubscriptionExpiringSoon(agent);

          return (
            <div
              className={`agent-card${!canEditAgent ? ' agent-card-readonly' : ''}${draggedId === agent.id ? ' agent-card-dragging' : ''}${dragOverId === agent.id ? ' agent-card-dragover' : ''}${derivedStatus.status !== 'available' ? ' agent-card-unavailable' : ''}`}
              key={agent.id}
              draggable={canEditAgent}
              title={readonlyTitle}
              onDragStart={(e) => {
                if (!canEditAgent) return;
                setDraggedId(agent.id);
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', String(agent.id));
              }}
              onDragEnd={() => { setDraggedId(null); setDragOverId(null); }}
              onDragOver={(e) => { if (!canEditAgent) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragOverId(agent.id); }}
              onDragLeave={() => { if (dragOverId === agent.id) setDragOverId(null); }}
              onDrop={(e) => {
                if (!canEditAgent) return;
                e.preventDefault();
                setDragOverId(null);
                if (draggedId != null && draggedId !== agent.id) {
                  handleReorder(draggedId, agent.id);
                }
                setDraggedId(null);
              }}
            >
              <div className="agent-card-top">
                <div className="agent-card-identity">
                  <span className="agent-card-drag-handle" title={canEditAgent ? '拖动排序' : '公共 Agent 仅创建者可维护'}>⠿</span>
                  <span className="agent-card-name">{agent.name}</span>
                  <span className={`badge ${agent.is_public ? 'badge-public' : 'badge-private'}`}>
                    {agent.is_public ? '公共' : '私有'}
                  </span>
                  {!agent.is_active && <span className="badge badge-disabled-public">已停用</span>}
                  <div className="agent-status-container" ref={statusDropdownAgentId === agent.id ? statusDropdownRef : undefined}>
                    <span
                      className="status-badge"
                      style={{
                        backgroundColor: `${derivedStatus.color}20`,
                        color: derivedStatus.color,
                        border: `1px solid ${derivedStatus.color}40`,
                        cursor: derivedStatus.canChangeStatus && canEditAgent ? 'pointer' : 'default',
                      }}
                      title={`当前状态：${derivedStatus.label}`}
                      onClick={() => {
                        if (derivedStatus.canChangeStatus && canEditAgent) {
                          setStatusDropdownAgentId((prev) => prev === agent.id ? null : agent.id);
                        }
                      }}
                    >
                      {derivedStatus.label}
                    </span>
                    {statusDropdownAgentId === agent.id && (
                      <div className="status-dropdown">
                        <div
                          className={`status-dropdown-item${derivedStatus.status === 'available' ? ' active' : ''}`}
                          onClick={() => handleStatusChange(agent.id, 'available')}
                        >
                          可用
                        </div>
                        <div
                          className={`status-dropdown-item${derivedStatus.status === 'short_reset_pending' ? ' active' : ''}${!agent.short_term_reset_at ? ' disabled' : ''}`}
                          onClick={() => agent.short_term_reset_at && handleStatusChange(agent.id, 'short_reset_pending')}
                          title={!agent.short_term_reset_at ? '未设置短期重置时间' : undefined}
                        >
                          短期重置后可用
                        </div>
                        <div
                          className={`status-dropdown-item${derivedStatus.status === 'long_reset_pending' ? ' active' : ''}${!agent.long_term_reset_at ? ' disabled' : ''}`}
                          onClick={() => agent.long_term_reset_at && handleStatusChange(agent.id, 'long_reset_pending')}
                          title={!agent.long_term_reset_at ? '未设置长期重置时间' : undefined}
                        >
                          长期重置后可用
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="agent-card-inline-actions">
                    <button className="btn btn-sm btn-edit" onClick={() => handleEdit(agent)} disabled={!canEditAgent} title={readonlyTitle}>编辑</button>
                    <button
                      className="btn btn-sm btn-edit"
                      onClick={() => handleActiveChange(agent, !agent.is_active)}
                      disabled={!canEditAgent || actionAgentId === agent.id}
                      title={readonlyTitle}
                    >
                      {agent.is_active ? '停用' : '启用'}
                    </button>
                    <button className="btn btn-sm btn-delete" onClick={() => handleDelete(agent)} disabled={!canEditAgent || deletingId === agent.id} title={readonlyTitle}>
                      {deletingId === agent.id ? '删除中' : '删除'}
                    </button>
                  </div>
                </div>
              </div>

              {typeDescriptionMap[agent.agent_type] && (
                <p className="agent-card-type-desc">{typeDescriptionMap[agent.agent_type]}</p>
              )}

              <div className="agent-card-badges">
                {getAgentModels(agent).map((model, index) => (
                  <ModelBadge key={`${agent.id}-${model.model_name}-${index}`} type={index === 0 ? agent.agent_type : undefined} model={model.model_name} />
                ))}
                {agent.co_located && <span className="badge badge-neutral" title="该 Agent 默认与项目部署机器同服务器">同服务器</span>}
                {expiryDisplay && <span className={`badge badge-expiry${expiringSoon ? ' badge-expiry-warning' : ''}`} title="订阅到期时间">{expiryDisplay}</span>}
              </div>

              {getAgentModels(agent).filter((model) => modelsWithCapability.has(`${agent.id}:${model.model_name}`)).length > 0 && (
                <div className="agent-model-capability-list">
                  {getAgentModels(agent).map((model, index) => {
                    if (!modelsWithCapability.has(`${agent.id}:${model.model_name}`)) return null;
                    return (
                      <p className="agent-card-capability" key={`${agent.id}-capability-${index}`}>
                        <strong>{model.model_name}</strong>
                        {model.capability ? `：${model.capability}` : ''}
                      </p>
                    );
                  })}
                </div>
              )}

              <div className="agent-card-resets">
                <CountdownChip
                  label="短期"
                  display={shortTerm.display}
                  tooltip={shortTerm.tooltip}
                  color={shortColor}
                  interval={agent.short_term_reset_interval_hours != null ? `${agent.short_term_reset_interval_hours}h` : undefined}
                  showActions={showShortActions}
                  onReset={() => handleResetAction(agent.id, 'short')}
                  onConfirm={() => handleConfirmAction(agent.id, 'short')}
                  disabled={actionAgentId === agent.id || !canEditAgent}
                />
                <CountdownChip
                  label="长期"
                  display={longTerm.display}
                  tooltip={longTerm.tooltip}
                  color={longColor}
                  interval={agent.long_term_reset_mode === 'monthly' ? (() => {
                    const p = parseStoredDateTime(agent.long_term_reset_at);
                    return p ? `每月${p.day}日` : '每月';
                  })() : agent.long_term_reset_interval_days != null ? `${agent.long_term_reset_interval_days}d` : undefined}
                  showActions={showLongActions}
                  onReset={() => handleResetAction(agent.id, 'long')}
                  onConfirm={() => handleConfirmAction(agent.id, 'long')}
                  disabled={actionAgentId === agent.id || !canEditAgent}
                />
              </div>
            </div>
          );
        })}
        {agents.length === 0 && (
          <div className="empty-state">当前还没有配置智能体。</div>
        )}
      </div>
    </div>
  );
}
