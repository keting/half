import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { copyText, getPlanIdToFinalize } from '../contracts';
import { Agent, Plan, ProcessTemplate, Project } from '../types';
import { getAgentModels } from '../utils/agents';
import { applyTemplatePlan, filterTemplateInputs, getMissingTemplateInputs } from '../utils/applyTemplatePlan';
import { FlowSource, buildPlanSourcePrefKey, resolveFlowSourcePreference } from '../utils/flowSource';
import { DEFAULT_PLANNING_MODE, PLANNING_MODE_OPTIONS, PlanningMode, getPlanningModeMeta, normalizePlanningMode } from '../utils/planningMode';

function formatDuration(seconds: number): string {
  const safeSeconds = Math.max(0, seconds);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

function getStatusMeta(plan: Plan | null) {
  if (!plan || plan.status === 'pending') {
    return { color: 'yellow', text: '未启动' };
  }
  if (plan.status === 'running') {
    return { color: 'red', text: '轮询中' };
  }
  if (plan.status === 'completed' || plan.status === 'final') {
    return { color: 'green', text: '已查询到规划结果' };
  }
  return { color: 'yellow', text: '已结束，未查询到结果' };
}

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [templates, setTemplates] = useState<ProcessTemplate[]>([]);
  const [flowSource, setFlowSource] = useState<FlowSource>('template');
  const [planningBrief, setPlanningBrief] = useState('');
  const [planningMode, setPlanningMode] = useState<PlanningMode>(DEFAULT_PLANNING_MODE);
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const [selectedAgentModels, setSelectedAgentModels] = useState<Record<number, string | null>>({});
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [slotAgentIds, setSlotAgentIds] = useState<Record<string, number | null>>({});
  const [templateInputs, setTemplateInputs] = useState<Record<string, string>>({});
  const [promptText, setPromptText] = useState('');
  const [currentPlanId, setCurrentPlanId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState('');
  const [error, setError] = useState('');
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [timerPlanId, setTimerPlanId] = useState<number | null>(null);
  const [isAutoFinalizing, setIsAutoFinalizing] = useState(false);
  const timerStartedAtRef = useRef<number | null>(null);
  const autoFinalizeTriggeredRef = useRef<number | null>(null);
  const didAutoSelectFlowSourceRef = useRef(false);
  const didUserSelectFlowSourceRef = useRef(false);
  const flowSourceProjectIdRef = useRef<string | null>(null);

  function updateFlowSource(next: FlowSource) {
    didUserSelectFlowSourceRef.current = true;
    if (project?.created_by && id) {
      localStorage.setItem(buildPlanSourcePrefKey(project.created_by, id), next);
    }
    setFlowSource(next);
  }

  const fetchPageData = useCallback(async () => {
    // 跨页面共享的 agents 走 stale-while-revalidate 缓存，避免每次切页都白屏等待。
    void api.getCached<Agent[]>('/api/agents', (value) => setAgents(value));
    void api.getCached<Project>(`/api/projects/${id}`, (value) => {
      setProject(value);
      setPlanningMode(normalizePlanningMode(value.planning_mode));
      setLoading(false);
    });
    try {
      const [projectData, planList, templateList] = await Promise.all([
        api.get<Project>(`/api/projects/${id}`),
        api.get<Plan[]>(`/api/projects/${id}/plans`),
        api.get<ProcessTemplate[]>('/api/process-templates'),
      ]);
      setProject(projectData);
      setPlans(planList);
      setTemplates(templateList);
      setPlanningBrief((current) => current || projectData.goal || '');
      setPlanningMode(normalizePlanningMode(projectData.planning_mode));
      setTemplateInputs((current) => Object.keys(current).length ? current : (projectData.template_inputs || {}));

      if (flowSourceProjectIdRef.current !== (id || null)) {
        flowSourceProjectIdRef.current = id || null;
        didAutoSelectFlowSourceRef.current = false;
        didUserSelectFlowSourceRef.current = false;
      }

      if (!didAutoSelectFlowSourceRef.current && !didUserSelectFlowSourceRef.current) {
        didAutoSelectFlowSourceRef.current = true;
        const storageKey = projectData.created_by && id ? buildPlanSourcePrefKey(projectData.created_by, id) : null;
        const storedPreference = storageKey ? localStorage.getItem(storageKey) : null;
        setFlowSource(resolveFlowSourcePreference(storedPreference, projectData.agent_ids, templateList));
      }

      const latestPlan = [...planList].reverse()[0] || null;
      if (latestPlan) {
        setPromptText(latestPlan.prompt_text || '');
        setCurrentPlanId(latestPlan.id);
        setSelectedAgentIds(latestPlan.selected_agent_ids?.length ? latestPlan.selected_agent_ids : (projectData.agent_ids || []));
        setSelectedAgentModels(latestPlan.selected_agent_models || {});
      } else {
        setPromptText('');
        setCurrentPlanId(null);
        setSelectedAgentIds(projectData.agent_ids || []);
        setSelectedAgentModels({});
      }
    } catch (err) {
      setError(`加载 Plan 页面失败：${err}`);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchPageData();
  }, [fetchPageData]);

  const projectAgents = useMemo(() => {
    if (!project?.agent_ids?.length) return agents;
    const projectAgentIds = project.agent_ids || [];
    return agents.filter((agent) => projectAgentIds.includes(agent.id));
  }, [agents, project]);

  const latestPlan = useMemo(() => [...plans].reverse()[0] || null, [plans]);
  const statusMeta = getStatusMeta(latestPlan);
  const planningModeMeta = getPlanningModeMeta(planningMode);
  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === selectedTemplateId) || null,
    [selectedTemplateId, templates]
  );
  const mappedAgentIds = useMemo(
    () => Object.values(slotAgentIds).filter((value): value is number => typeof value === 'number'),
    [slotAgentIds]
  );
  const templateMappingComplete = Boolean(
    selectedTemplate
    && selectedTemplate.agent_slots.every((slot) => typeof slotAgentIds[slot] === 'number')
    && new Set(mappedAgentIds).size === mappedAgentIds.length
  );
  const planningBriefMissing = !planningBrief.trim();
  const missingTemplateInputs = useMemo(
    () => getMissingTemplateInputs(selectedTemplate?.required_inputs || [], templateInputs),
    [selectedTemplate, templateInputs]
  );
  const templateInputsMissing = missingTemplateInputs.length > 0;

  useEffect(() => {
    if (!latestPlan || latestPlan.status !== 'running') {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void fetchPageData();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [fetchPageData, latestPlan]);

  useEffect(() => {
    if (latestPlan?.status !== 'running' || timerPlanId !== latestPlan.id || timerStartedAtRef.current === null) {
      setElapsedSeconds(0);
      return undefined;
    }

    const updateElapsed = () => {
      setElapsedSeconds(Math.floor((Date.now() - timerStartedAtRef.current!) / 1000));
    };

    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [latestPlan?.id, latestPlan?.status, timerPlanId]);

  useEffect(() => {
    if (!latestPlan || latestPlan.status === 'running') {
      return;
    }
    setTimerPlanId(null);
    timerStartedAtRef.current = null;
    setElapsedSeconds(0);
  }, [latestPlan]);

  useEffect(() => {
    if (!latestPlan || latestPlan.status !== 'running') return undefined;

    const refreshOnFocus = () => {
      void fetchPageData();
    };
    const refreshOnVisible = () => {
      if (document.visibilityState === 'visible') {
        void fetchPageData();
      }
    };

    window.addEventListener('focus', refreshOnFocus);
    document.addEventListener('visibilitychange', refreshOnVisible);
    return () => {
      window.removeEventListener('focus', refreshOnFocus);
      document.removeEventListener('visibilitychange', refreshOnVisible);
    };
  }, [fetchPageData, latestPlan]);

  function toggleSelectedAgent(agentId: number) {
    setSelectedAgentIds((current) => {
      const isSelected = current.includes(agentId);
      setSelectedAgentModels((currentModels) => {
        if (!isSelected) {
          return currentModels;
        }
        const next = { ...currentModels };
        delete next[agentId];
        return next;
      });
      return isSelected ? current.filter((idValue) => idValue !== agentId) : [...current, agentId];
    });
  }

  function updateSelectedAgentModel(agentId: number, modelName: string) {
    setSelectedAgentModels((current) => {
      const next = { ...current };
      if (!modelName) {
        delete next[agentId];
      } else {
        next[agentId] = modelName;
      }
      return next;
    });
  }

  function handleSelectTemplate(templateId: number) {
    const template = templates.find((item) => item.id === templateId) || null;
    setSelectedTemplateId(templateId);
    setSlotAgentIds(Object.fromEntries((template?.agent_slots || []).map((slot) => [slot, null])));
    setTemplateInputs((current) => filterTemplateInputs(template?.required_inputs || [], current));
  }

  function updateSlotAgent(slot: string, agentIdValue: string) {
    setSlotAgentIds((current) => ({
      ...current,
      [slot]: agentIdValue ? Number(agentIdValue) : null,
    }));
  }

  function updateTemplateInput(key: string, value: string) {
    setTemplateInputs((current) => ({ ...current, [key]: value }));
  }

  async function handleApplyTemplate() {
    setActionLoading('apply-template');
    setError('');
    try {
      await applyTemplatePlan({
        api,
        projectId: id,
        templateId: selectedTemplate?.id ?? null,
        planningBrief,
        slotAgentIds,
        templateMappingComplete,
        requiredInputs: selectedTemplate?.required_inputs || [],
        templateInputs,
      });
      api.invalidate(`/api/projects/${id}`);
      navigate(`/projects/${id}/tasks`);
    } catch (err) {
      setError(`应用流程模版失败：${err}`);
    } finally {
      setActionLoading('');
    }
  }

  async function handleGeneratePrompt() {
    setActionLoading('generate');
    setError('');
    try {
      if (!planningBrief.trim()) {
        throw new Error('请先填写任务介绍。');
      }
      if (selectedAgentIds.length === 0) {
        throw new Error('请至少勾选 1 个参与规划的 Agent。');
      }

      await api.put<Project>(`/api/projects/${id}`, { goal: planningBrief, planning_mode: planningMode });
      const result = await api.post<{ prompt: string; plan_id: number; source_path: string }>(
        `/api/projects/${id}/plans/generate-prompt`,
        {
          selected_agent_ids: selectedAgentIds,
          selected_agent_models: selectedAgentModels,
        }
      );
      setPromptText(result.prompt);
      setCurrentPlanId(result.plan_id);
      await fetchPageData();
    } catch (err) {
      setError(`生成 Prompt 失败：${err}`);
    } finally {
      setActionLoading('');
    }
  }

  async function handleCopyPrompt() {
    setActionLoading('copy');
    setError('');
    try {
      if (!promptText.trim() || !currentPlanId) {
        throw new Error('请先生成 Prompt。');
      }

      const copied = await copyText(promptText, navigator.clipboard);
      if (!copied) {
        throw new Error('浏览器未能自动复制，请检查页面权限。');
      }

      const dispatchedPlan = await api.post<Plan>(`/api/projects/${id}/plans/${currentPlanId}/dispatch`);
      timerStartedAtRef.current = Date.now();
      setTimerPlanId(dispatchedPlan.id);
      setElapsedSeconds(0);
      setCurrentPlanId(dispatchedPlan.id);
      setPlans((current) => {
        const others = current.filter((plan) => plan.id !== dispatchedPlan.id);
        return [...others, dispatchedPlan].sort((left, right) => left.id - right.id);
      });
      await fetchPageData();
    } catch (err) {
      setError(`拷贝 Prompt 失败：${err}`);
    } finally {
      setActionLoading('');
    }
  }

  async function handleRefreshPlanStatus() {
    setActionLoading('poll');
    setError('');
    try {
      await api.post(`/api/projects/${id}/poll`);
      await fetchPageData();
    } catch (err) {
      setError(`刷新规划状态失败：${err}`);
    } finally {
      setActionLoading('');
    }
  }

  const handleFinalize = useCallback(async (navigateAfterFinalize: boolean) => {
    const completedPlans = plans.filter((plan) => (plan.status === 'completed' || plan.status === 'final') && plan.plan_json);
    const planId = getPlanIdToFinalize(completedPlans);
    if (!planId) {
      setError('当前还没有可确认的规划结果。');
      return;
    }
    setActionLoading('finalize');
    setError('');
    try {
      await api.post(`/api/projects/${id}/plans/finalize`, { plan_id: planId });
      if (navigateAfterFinalize) {
        navigate(`/projects/${id}/tasks`);
      } else {
        await fetchPageData();
      }
    } catch (err) {
      const message = String(err);
      if (message.includes('Project already has tasks from a finalized plan')) {
        navigate(`/projects/${id}/tasks`);
        return;
      }
      setError(`确认规划失败：${err}`);
    } finally {
      setActionLoading('');
    }
  }, [fetchPageData, id, navigate, plans]);

  useEffect(() => {
    if (!latestPlan || isAutoFinalizing) return;
    if (latestPlan.status === 'final') {
      navigate(`/projects/${id}/tasks`);
      return;
    }
    if (latestPlan.status !== 'completed' || !latestPlan.plan_json) {
      autoFinalizeTriggeredRef.current = null;
      return;
    }
    if (autoFinalizeTriggeredRef.current === latestPlan.id) {
      return;
    }

    autoFinalizeTriggeredRef.current = latestPlan.id;
    setIsAutoFinalizing(true);
    void handleFinalize(true).finally(() => {
      setIsAutoFinalizing(false);
    });
  }, [handleFinalize, id, isAutoFinalizing, latestPlan, navigate]);

  if (loading) return <div className="page-loading">正在加载 Plan...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1>Plan 规划</h1>
        <div className="header-actions">
          <button className="btn btn-secondary" onClick={handleRefreshPlanStatus} disabled={actionLoading === 'poll'}>
            {actionLoading === 'poll' ? '刷新中...' : '刷新规划状态'}
          </button>
          <button className="btn btn-ghost" onClick={() => navigate(`/projects/${id}`)}>
            返回项目
          </button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="plan-layout">
        <div className="plan-main-column">
          <section className="plan-card">
            <div className="plan-card-header">
              <div>
                <h3>1. 任务介绍</h3>
                <p>描述本次项目目标、边界和验收标准；选择任一流程来源继续时会自动保存当前内容。</p>
              </div>
            </div>
            <textarea
              value={planningBrief}
              onChange={(event) => setPlanningBrief(event.target.value)}
              rows={6}
              className="import-textarea"
              placeholder="请填写本次项目规划的任务介绍、目标、边界和验收标准。"
            />
            <div className="helper-text">任务介绍会保存到项目中，并用于后续规划或任务执行上下文。</div>
          </section>

          <section className="plan-card">
            <div className="plan-card-header">
              <div>
                <h3>2. 选择流程来源</h3>
                <p>可由 Prompt 生成新的流程，也可直接使用已保存的流程模版生成任务。</p>
              </div>
            </div>

            <div className="plan-field">
              <label>流程来源</label>
              <div className="flow-source-segmented" role="radiogroup" aria-label="流程来源">
                <label className={`flow-source-segment ${flowSource === 'template' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="flow-source"
                    checked={flowSource === 'template'}
                    onChange={() => updateFlowSource('template')}
                  />
                  <span>使用模版生成流程</span>
                </label>
                <label className={`flow-source-segment ${flowSource === 'prompt' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="flow-source"
                    checked={flowSource === 'prompt'}
                    onChange={() => updateFlowSource('prompt')}
                  />
                  <span>由 Prompt 生成流程</span>
                </label>
              </div>
              <div className="flow-source-hint helper-text" aria-live="polite">
                {flowSource === 'prompt'
                  ? '生成规划 Prompt，交给外部 Agent 产出 plan JSON。'
                  : '选择已有模版，完成角色映射后直接生成任务。'}
              </div>
            </div>

            {flowSource === 'prompt' && (
              <>
                <div className="plan-field">
                  <label>规划模式</label>
                  <div className="planning-mode-options" role="radiogroup" aria-label="项目规划模式">
                    {PLANNING_MODE_OPTIONS.map((option) => (
                      <label key={option.value} className={`planning-mode-option ${planningMode === option.value ? 'selected' : ''}`}>
                        <input
                          type="radio"
                          name="planning-mode"
                          value={option.value}
                          checked={planningMode === option.value}
                          onChange={() => setPlanningMode(option.value)}
                        />
                        <span className="planning-mode-option-copy">
                          <span className="planning-mode-option-label">{option.label}</span>
                          <span className="planning-mode-option-description">{option.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="plan-field">
                  <label>本次参与规划的 Agent</label>
                  <div className="plan-agent-grid">
                    {projectAgents.map((agent) => (
                      <div key={agent.id} className={`agent-option ${selectedAgentIds.includes(agent.id) ? 'selected' : ''}`}>
                        <label className="agent-option-check">
                          <input
                            type="checkbox"
                            checked={selectedAgentIds.includes(agent.id)}
                            onChange={() => toggleSelectedAgent(agent.id)}
                          />
                          <span className="agent-option-name">{agent.name}</span>
                          {' '}
                          <span className="agent-option-type">{agent.agent_type}</span>
                          {' '}
                          <span className={`badge ${agent.is_public ? 'badge-public' : 'badge-private'}`}>
                            {agent.is_public ? '公共' : '私有'}
                          </span>
                          {agent.is_disabled_public && <span className="badge badge-disabled-public">已停用</span>}
                        </label>
                        <span className="agent-option-model-list">
                          {getAgentModels(agent).map((model) => model.model_name).join(' / ') || '未配置模型'}
                        </span>
                        {selectedAgentIds.includes(agent.id) && getAgentModels(agent).length > 0 && (
                          <div className="agent-option-model-picker">
                            <label>本项目使用模型</label>
                            <select
                              value={selectedAgentModels[agent.id] || ''}
                              onChange={(event) => updateSelectedAgentModel(agent.id, event.target.value)}
                            >
                              <option value="">自动选择最适合的模型</option>
                              {getAgentModels(agent).map((model) => (
                                <option key={model.model_name} value={model.model_name}>
                                  {model.model_name}{model.capability ? ` | ${model.capability}` : ''}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="plan-field">
                  <label>本次发给 Agent 的 Prompt</label>
                  <textarea
                    value={promptText}
                    onChange={(event) => setPromptText(event.target.value)}
                    rows={10}
                    className="import-textarea"
                    placeholder="点击“生成 Prompt”后，这里会显示本次规划 Prompt。"
                  />
                </div>

                <div className="plan-prompt-actions">
                  <button className="btn btn-secondary" onClick={handleGeneratePrompt} disabled={actionLoading === 'generate'}>
                    {actionLoading === 'generate' ? '生成中...' : '生成 Prompt'}
                  </button>
                  <button className="btn btn-primary" onClick={handleCopyPrompt} disabled={actionLoading === 'copy' || !promptText.trim() || !currentPlanId}>
                    {actionLoading === 'copy' ? '拷贝中...' : '拷贝 Prompt'}
                  </button>
                </div>

                <div className="plan-status-banner">
                  <div className="plan-status-line">
                    <span className={`status-light status-light-${statusMeta.color}`} />
                    <strong>当前状态：</strong>
                    <span>{statusMeta.text}</span>
                  </div>
                  <div>
                    <strong>轮询路径：</strong>{latestPlan?.source_path || (project?.collaboration_dir ? `${project.collaboration_dir}/plan.json` : 'plan.json')}
                  </div>
                  {latestPlan?.status === 'running' && timerPlanId === latestPlan.id && (
                    <div>
                      <strong>已运行：</strong>{formatDuration(elapsedSeconds)}
                    </div>
                  )}
                  {isAutoFinalizing && <div>已查询到规划结果，正在自动进入下一页...</div>}
                  {latestPlan?.last_error && <div className="plan-status-error">{latestPlan.last_error}</div>}
                </div>
              </>
            )}

            {flowSource === 'template' && (
              <>
                <div className="plan-field">
                  <label>流程模版</label>
                  <div className="template-select-list">
                    {templates.map((template) => {
                      const disabled = projectAgents.length < template.agent_count;
                      return (
                        <button
                          type="button"
                          key={template.id}
                          className={`template-select-item ${selectedTemplateId === template.id ? 'selected' : ''}`}
                          onClick={() => handleSelectTemplate(template.id)}
                          disabled={disabled}
                        >
                          <strong>{template.name}</strong>
                          <span>{template.description || '暂无适用场景说明'}</span>
                          <small>需要 {template.agent_count} 个 Agent：{template.agent_slots.join(' / ')}</small>
                          {disabled && <small className="template-warning">当前项目 Agent 数量不足</small>}
                        </button>
                      );
                    })}
                    {!templates.length && <div className="helper-text">还没有流程模版，请先到“流程模版”页面创建。</div>}
                  </div>
                </div>

                {selectedTemplate && (
                  <div className="plan-field">
                    <label>角色映射</label>
                    <div className="template-slot-map">
                      {selectedTemplate.agent_slots.map((slot) => {
                        const selectedAgentId = slotAgentIds[slot] ?? null;
                        return (
                          <div key={slot} className="template-slot-row">
                            <div className="template-slot-row-main">
                              <span className="template-slot-name">{slot}</span>
                              <select
                                value={selectedAgentId ?? ''}
                                onChange={(event) => updateSlotAgent(slot, event.target.value)}
                              >
                                <option value="">选择 Agent</option>
                                {projectAgents.map((agent) => (
                                  <option
                                    key={agent.id}
                                    value={agent.id}
                                    disabled={mappedAgentIds.includes(agent.id) && selectedAgentId !== agent.id}
                                  >
                                    {agent.name} ({agent.agent_type})
                                    {agent.is_public ? ' · 公共' : ''}
                                    {agent.is_disabled_public ? ' · 已停用' : ''}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div className="template-slot-description">
                              {selectedTemplate.agent_roles_description?.[slot] || '暂无说明'}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {mappedAgentIds.length !== new Set(mappedAgentIds).size && (
                      <div className="helper-text helper-text-error">不允许多个槽位映射到同一个 Agent。</div>
                    )}
                  </div>
                )}

                {selectedTemplate && (selectedTemplate.required_inputs || []).length > 0 && (
                  <div className="plan-field">
                    <label>模版所需信息</label>
                    <div className="template-slot-map">
                      {(selectedTemplate.required_inputs || []).map((input) => {
                        const value = templateInputs[input.key] || '';
                        const missing = input.required && !value.trim();
                        return (
                          <div key={input.key} className="template-slot-row">
                            <div className="template-slot-row-main">
                              <label htmlFor={`template-input-${input.key}`}>
                                {input.label}{input.required && <span className="helper-text-error"> *</span>}
                              </label>
                              <input
                                id={`template-input-${input.key}`}
                                type={input.sensitive ? 'password' : 'text'}
                                value={value}
                                onChange={(event) => updateTemplateInput(input.key, event.target.value)}
                                placeholder={input.label}
                              />
                            </div>
                            <div className="template-slot-description">
                              {input.key}{input.sensitive ? ' · 敏感输入' : ''}
                            </div>
                            {missing && <div className="helper-text helper-text-error">必填</div>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="plan-prompt-actions">
                  {planningBriefMissing && (
                    <div className="helper-text helper-text-error">请先填写任务介绍。</div>
                  )}
                  {templateInputsMissing && (
                    <div className="helper-text helper-text-error">请填写所有模版所需信息。</div>
                  )}
                  <button
                    className="btn btn-primary"
                    onClick={handleApplyTemplate}
                    disabled={actionLoading === 'apply-template' || planningBriefMissing || !templateMappingComplete || templateInputsMissing}
                  >
                    {actionLoading === 'apply-template' ? '生成中...' : '下一步'}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>

        <aside className="plan-side-column">

          {flowSource === 'prompt' && (
            <section className="plan-card">
              <h3>当前模式</h3>
              <div className="plan-mode-summary">
                <strong>{planningModeMeta.label}</strong>
                <p>{planningModeMeta.description}</p>
              </div>
            </section>
          )}

          <section className="plan-card">
            <h3>当前说明</h3>
            <ul className="plan-note-list">
              {flowSource === 'prompt' ? (
                <>
                  <li>点击“生成 Prompt”只会生成提示词，不会启动轮询。</li>
                  <li>点击“拷贝 Prompt”后才会正式启动或恢复本次规划的轮询。</li>
                  <li>若轮询已完成，再次点击“拷贝 Prompt”会启动新一轮轮询。</li>
                  <li>每个参与规划的 Agent 都可以手动指定一个模型；留空时系统会根据任务目标和模型能力自动选择。</li>
                  <li>每一轮规划都会使用唯一文件名，例如 `plan-123.json`，避免复用旧结果。</li>
                  <li>查询到合法规划结果后，系统会自动定稿并跳转到执行页面。</li>
                </>
              ) : (
                <>
                  <li>模版路径不会生成 Prompt，也不会启动规划轮询。</li>
                  <li>每个角色槽位必须映射到一个项目已选 Agent。</li>
                  <li>同一个 Agent 不能同时映射到多个槽位。</li>
                  <li>点击“下一步”后会直接生成任务并进入执行页面。</li>
                </>
              )}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
