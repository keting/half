import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Task, Agent, Project, FlowState } from '../types';
import DagView from '../components/DagView';
import TaskDetailPanel from '../components/TaskDetailPanel';
import { getNextStepText } from '../contracts';
import { ISSUE_REVIEW_LOOP_ATTENTION_MESSAGE, hasIssueReviewLoopAttention } from '../utils/issueReviewLoop';

export default function TasksPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [flowState, setFlowState] = useState<FlowState | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const lastFetchAtRef = React.useRef<number>(0);

  const fetchData = useCallback(async () => {
    lastFetchAtRef.current = Date.now();
    // 跨页面共享的 /api/agents、/api/projects/:id 走 stale-while-revalidate 缓存：
    // 命中时立刻渲染旧值，再后台刷新；这样切回任务页时不会再整页白屏。
    void api.getCached<Agent[]>('/api/agents', (value) => setAgents(value));
    void api.getCached<Project>(`/api/projects/${id}`, (value) => {
      setProject(value);
      setLoading(false);
    });
    try {
      const [taskList, flowStateData] = await Promise.all([
        api.get<Task[]>(`/api/projects/${id}/tasks`),
        api.get<FlowState>(`/api/projects/${id}/flow-state`).catch(() => null),
      ]);
      setTasks(taskList);
      setFlowState(flowStateData);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const hasActiveWork = Boolean(
      project && ['planning', 'executing'].includes(project.status)
    ) || tasks.some((task) => task.status === 'running');
    if (!hasActiveWork) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void fetchData();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [fetchData, project, tasks]);

  useEffect(() => {
    // focus / visibilitychange 上的刷新做 2s 节流，避免与 5s 轮询、
    // React StrictMode 双调用、以及快速切页叠加在一起。
    const THROTTLE_MS = 2000;
    const maybeRefresh = () => {
      if (Date.now() - lastFetchAtRef.current < THROTTLE_MS) return;
      void fetchData();
    };
    const refreshOnFocus = () => maybeRefresh();
    const refreshOnVisible = () => {
      if (document.visibilityState === 'visible') maybeRefresh();
    };

    window.addEventListener('focus', refreshOnFocus);
    document.addEventListener('visibilitychange', refreshOnVisible);
    return () => {
      window.removeEventListener('focus', refreshOnFocus);
      document.removeEventListener('visibilitychange', refreshOnVisible);
    };
  }, [fetchData]);

  async function handleManualRefresh() {
    setRefreshing(true);
    try {
      await api.post(`/api/projects/${id}/poll`);
      await fetchData();
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) || null;
  const nextStepText = getNextStepText(project?.next_step);
  const showIssueReviewLoopAttention = hasIssueReviewLoopAttention(flowState);
  const tasksWithAgentLabels = tasks.map((task) => {
    const assignee = agents.find((agent) => agent.id === task.assignee_agent_id);
    return {
      ...task,
      assignee_label: assignee ? assignee.name : null,
      business_status: flowState?.enabled ? flowState.effective_task_states?.[task.task_code] : null,
    };
  });

  if (loading) return <div className="page-loading">正在加载任务...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1>计划修改与执行</h1>
        <div className="header-actions">
          <button
            className="btn btn-secondary"
            onClick={handleManualRefresh}
            disabled={refreshing}
            title="主动轮询后端状态，刷新任务进度和项目状态"
          >
            {refreshing ? '刷新中...' : '手动刷新'}
          </button>
          <button className="btn btn-ghost" onClick={() => navigate(`/projects/${id}`)} title="返回项目详情页">
            返回项目
          </button>
        </div>
      </div>

      {nextStepText && (
        <div className="next-step-banner">
          <strong>下一步：</strong> {nextStepText}
        </div>
      )}

      {flowState?.enabled && (
        <div className="next-step-banner">
          <strong>评审循环：</strong>
          {' '}
          阶段 {flowState.derived_phase || flowState.phase || '-'}，
          轮次 {flowState.current_round ?? '-'}，
          分支 {flowState.work_branch || '-'}，
          commit {flowState.head_commit || '-'}
          {flowState.pr?.url && (
            <>
              {' '}，PR <a href={flowState.pr.url} target="_blank" rel="noreferrer">{flowState.pr.url}</a>
            </>
          )}
          {flowState.reviews?.['TASK-003'] && (
            <>，评审 A {flowState.reviews['TASK-003'].status}{typeof flowState.reviews['TASK-003'].approve_merge === 'boolean' ? ` / ${flowState.reviews['TASK-003'].approve_merge ? '同意' : '不同意'}` : ''}</>
          )}
          {flowState.reviews?.['TASK-004'] && (
            <>，评审 B {flowState.reviews['TASK-004'].status}{typeof flowState.reviews['TASK-004'].approve_merge === 'boolean' ? ` / ${flowState.reviews['TASK-004'].approve_merge ? '同意' : '不同意'}` : ''}</>
          )}
          {flowState.errors?.length > 0 && (
            <div className="helper-text helper-text-error">{flowState.errors.join('；')}</div>
          )}
          {showIssueReviewLoopAttention && (
            <div className="helper-text helper-text-warning">{ISSUE_REVIEW_LOOP_ATTENTION_MESSAGE}</div>
          )}
        </div>
      )}

      <div className="tasks-layout">
        <div className="tasks-dag-panel">
          <DagView
            tasks={tasksWithAgentLabels}
            selectedTaskId={selectedTaskId}
            onSelectTask={setSelectedTaskId}
            missingPredecessorIds={new Set()}
            showIssueReviewLoopEdge={flowState?.enabled}
          />
        </div>
        <div className="tasks-detail-panel">
          {selectedTask ? (
            <TaskDetailPanel
              task={selectedTask}
              agents={agents}
              allTasks={tasks}
              flowState={flowState}
              onRefresh={fetchData}
            />
          ) : (
            <div className="empty-panel">
              <p>请选择左侧任务节点以查看详情。</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
