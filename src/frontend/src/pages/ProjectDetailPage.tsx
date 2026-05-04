import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';
import StatusBadge from '../components/StatusBadge';
import ModelBadge from '../components/ModelBadge';
import { Agent, Project, Task } from '../types';
import { getNextStepAction, getNextStepText } from '../contracts';
import { formatDateTime } from '../utils/datetime';
import { validateGitRepoUrl } from '../utils/gitRepoUrl';
import { createInactiveProjectAgent } from '../utils/agents';

interface PredecessorStatus {
  task_id: number;
  ready: boolean;
  missing: Array<{
    task_code: string;
    task_name: string;
    expected_path: string;
  }>;
}

interface TaskWithReadiness extends Task {
  readiness?: PredecessorStatus;
}

export function formatBlockedPredecessor(item: PredecessorStatus['missing'][number]) {
  if (item.task_name && item.task_name !== '(未知)') {
    return `等待 ${item.task_code}（${item.task_name}）完成`;
  }
  return `等待 ${item.task_code} 完成`;
}

function getTaskTiming(task: Task) {
  if (task.status === 'completed' && task.completed_at) {
    return `完成于 ${formatDateTime(task.completed_at)}`;
  }
  if (task.status === 'running' && task.dispatched_at) {
    return `派发于 ${formatDateTime(task.dispatched_at)}`;
  }
  return '等待执行';
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [predecessorStatuses, setPredecessorStatuses] = useState<PredecessorStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    void api.getCached<Project>(`/api/projects/${id}`, (value) => {
      setProject(value);
      setLoading(false);
    });
    void api.getCached<Agent[]>('/api/agents', (value) => setAgents(value));

    try {
      const [projectDetail, taskList, agentList, statuses] = await Promise.all([
        api.get<Project>(`/api/projects/${id}`),
        api.get<Task[]>(`/api/projects/${id}/tasks`).catch(() => []),
        api.get<Agent[]>('/api/agents').catch(() => []),
        api.get<PredecessorStatus[]>(`/api/projects/${id}/predecessor-status`).catch(() => []),
      ]);
      setProject(projectDetail);
      setTasks(taskList);
      setAgents(agentList);
      setPredecessorStatuses(statuses);
    } catch {
      // ignore
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!project || !['planning', 'executing'].includes(project.status)) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void fetchData();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [fetchData, project?.status]);

  async function handleRefresh() {
    setRefreshing(true);
    await fetchData();
  }

  if (loading) {
    return <div className="page-loading">正在加载项目...</div>;
  }

  if (!project) {
    return <div className="page-loading">未找到该项目。</div>;
  }

  const summary = project.task_summary;
  const repoUrlError = validateGitRepoUrl(project.git_repo_url);
  const nextStepText = getNextStepText(project.next_step);
  const nextStepAction = getNextStepAction(project.next_step);
  const readinessMap = new Map(predecessorStatuses.map((status) => [status.task_id, status]));
  const tasksWithReadiness: TaskWithReadiness[] = tasks.map((task) => ({
    ...task,
    readiness: readinessMap.get(task.id),
  }));
  const selectedAgents = (() => {
    const projectAgentIds = project.agent_ids || [];
    const visibleSelectedAgents = agents.filter((agent) => projectAgentIds.includes(agent.id));
    const visibleIds = new Set(visibleSelectedAgents.map((agent) => agent.id));
    const missingInactiveAgents = (project.inactive_agent_ids || [])
      .filter((agentId) => projectAgentIds.includes(agentId) && !visibleIds.has(agentId))
      .map(createInactiveProjectAgent);
    return [...visibleSelectedAgents, ...missingInactiveAgents];
  })();
  const assignmentMap = new Map((project.agent_assignments || []).map((assignment) => [assignment.id, assignment.co_located]));
  const availableAgents = selectedAgents.filter((agent) => agent.availability_status === 'available');
  const runningTasks = tasksWithReadiness.filter((task) => task.status === 'running');
  const attentionTasks = tasksWithReadiness.filter((task) => task.status === 'needs_attention');
  const readyTasks = tasksWithReadiness.filter(
    (task) => task.status === 'pending' && task.readiness?.ready,
  );
  const blockedTasks = tasksWithReadiness.filter(
    (task) => task.status === 'pending' && task.readiness && !task.readiness.ready,
  );

  return (
    <div className="page project-console-page">
      <PageHeader title={project.name} description="前端最小可用协同面板，聚合项目、任务和 Agent 的关键状态。">
        <button
          className="btn btn-secondary"
          onClick={handleRefresh}
          disabled={refreshing}
          title="重新拉取项目、任务、前序依赖和 Agent 状态"
        >
          {refreshing ? '刷新中...' : '手动刷新'}
        </button>
      </PageHeader>

      {nextStepText && (
        <div className="next-step-banner">
          <strong>下一步：</strong> {nextStepText}
          {nextStepAction && (
            <span className="next-step-action">（{nextStepAction}）</span>
          )}
        </div>
      )}

      <div className="project-console-grid">
        <SectionCard
          title="项目概览"
          description="展示当前项目状态、仓库位置和协作目录。"
          className="project-console-card"
        >
          <div className="project-console-meta">
            <div className="project-console-meta-row">
              <span className="project-console-label">状态</span>
              <StatusBadge status={project.status} />
            </div>
            <div className="project-console-meta-row">
              <span className="project-console-label">项目目标</span>
              <p>{project.goal || '未填写项目目标'}</p>
            </div>
            <div className="project-console-meta-row">
              <span className="project-console-label">仓库地址</span>
              <div>
                <p className="project-console-code">{project.git_repo_url || '-'}</p>
                {repoUrlError && <div className="helper-text helper-text-error">{repoUrlError}</div>}
              </div>
            </div>
            <div className="project-console-meta-row">
              <span className="project-console-label">协作目录</span>
              <p className="project-console-code">{project.collaboration_dir || '-'}</p>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          title="执行快照"
          description="汇总任务总量、运行量和待处理量。"
          className="project-console-card"
        >
          <div className="task-summary-grid project-console-summary-grid">
            <div className="summary-card">
              <span className="summary-number">{summary?.total ?? tasks.length}</span>
              <span className="summary-label">总任务数</span>
            </div>
            <div className="summary-card">
              <span className="summary-number project-console-pending">{summary?.pending ?? 0}</span>
              <span className="summary-label">待处理</span>
            </div>
            <div className="summary-card">
              <span className="summary-number project-console-running">{summary?.running ?? 0}</span>
              <span className="summary-label">运行中</span>
            </div>
            <div className="summary-card">
              <span className="summary-number project-console-success">{summary?.completed ?? 0}</span>
              <span className="summary-label">已完成</span>
            </div>
            <div className="summary-card">
              <span className="summary-number project-console-warning">{summary?.needs_attention ?? 0}</span>
              <span className="summary-label">需关注</span>
            </div>
            <div className="summary-card">
              <span className="summary-number">{availableAgents.length}</span>
              <span className="summary-label">可用 Agent</span>
            </div>
          </div>
        </SectionCard>
      </div>

      <SectionCard
        title="任务队列"
        description="按照准备就绪、运行中、阻塞和需关注四类展示最关键执行信号。"
      >
        <div className="project-console-columns">
          <div className="project-console-column">
            <div className="project-console-column-header">
              <h3>准备执行</h3>
              <span>{readyTasks.length}</span>
            </div>
            {readyTasks.length > 0 ? (
              readyTasks.map((task) => (
                <div key={task.id} className="task-queue-card task-queue-card-ready">
                  <div className="task-queue-top">
                    <span className="code-cell">{task.task_code}</span>
                    <StatusBadge status={task.status} />
                  </div>
                  <strong>{task.task_name}</strong>
                  <p>{task.description || '暂无任务描述'}</p>
                  <span className="task-queue-meta">{getTaskTiming(task)}</span>
                </div>
              ))
            ) : (
              <div className="project-console-empty">当前没有已解锁的待执行任务。</div>
            )}
          </div>

          <div className="project-console-column">
            <div className="project-console-column-header">
              <h3>运行中</h3>
              <span>{runningTasks.length}</span>
            </div>
            {runningTasks.length > 0 ? (
              runningTasks.map((task) => (
                <div key={task.id} className="task-queue-card">
                  <div className="task-queue-top">
                    <span className="code-cell">{task.task_code}</span>
                    <StatusBadge status={task.status} />
                  </div>
                  <strong>{task.task_name}</strong>
                  <p>{task.description || '暂无任务描述'}</p>
                  <span className="task-queue-meta">{getTaskTiming(task)}</span>
                </div>
              ))
            ) : (
              <div className="project-console-empty">当前没有正在执行的任务。</div>
            )}
          </div>

          <div className="project-console-column">
            <div className="project-console-column-header">
              <h3>阻塞</h3>
              <span>{blockedTasks.length}</span>
            </div>
            {blockedTasks.length > 0 ? (
              blockedTasks.map((task) => (
                <div key={task.id} className="task-queue-card task-queue-card-blocked">
                  <div className="task-queue-top">
                    <span className="code-cell">{task.task_code}</span>
                    <StatusBadge status={task.status} />
                  </div>
                  <strong>{task.task_name}</strong>
                  <p>{task.description || '暂无任务描述'}</p>
                  <div className="task-queue-warning-list">
                    {task.readiness?.missing.map((item) => (
                      <div key={`${task.id}-${item.task_code}`} className="task-queue-warning-item">
                        {formatBlockedPredecessor(item)}
                      </div>
                    ))}
                  </div>
                </div>
              ))
            ) : (
              <div className="project-console-empty">当前没有被前置任务阻塞的待处理任务。</div>
            )}
          </div>

          <div className="project-console-column">
            <div className="project-console-column-header">
              <h3>需关注</h3>
              <span>{attentionTasks.length}</span>
            </div>
            {attentionTasks.length > 0 ? (
              attentionTasks.map((task) => (
                <div key={task.id} className="task-queue-card task-queue-card-attention">
                  <div className="task-queue-top">
                    <span className="code-cell">{task.task_code}</span>
                    <StatusBadge status={task.status} />
                  </div>
                  <strong>{task.task_name}</strong>
                  <p>{task.last_error || task.description || '等待人工处理'}</p>
                  <span className="task-queue-meta">{getTaskTiming(task)}</span>
                </div>
              ))
            ) : (
              <div className="project-console-empty">当前没有需要人工介入的任务。</div>
            )}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="执行 Agent"
        description="展示当前项目已选 Agent 的可用性、模型配置和订阅到期时间。"
      >
        <div className="project-console-agent-list">
          {selectedAgents.length > 0 ? (
            selectedAgents.map((agent) => (
              <div key={agent.id} className="project-console-agent-card">
                <div className="project-console-agent-top">
                  <div>
                    <strong>{agent.name}</strong>
                    <div className="project-console-agent-meta">
                      <ModelBadge type={agent.agent_type} model={agent.model_name} />
                      <span className={`badge ${agent.is_public ? 'badge-public' : 'badge-private'}`}>
                        {agent.is_public ? '公共' : '私有'}
                      </span>
                      {agent.is_disabled_public && <span className="badge badge-disabled-public">已停用</span>}
                    </div>
                  </div>
                  <StatusBadge status={agent.availability_status} />
                </div>
                <p className="project-console-agent-capability">
                  {agent.capability || '未填写能力说明'}
                </p>
                <div className="project-console-agent-footer">
                  <span>同服务器：{assignmentMap.get(agent.id) ? '是' : '否'}</span>
                  <span>订阅到期：{formatDateTime(agent.subscription_expires_at)}</span>
                </div>
              </div>
            ))
          ) : (
            <div className="project-console-empty">当前项目还没有绑定 Agent。</div>
          )}
        </div>
      </SectionCard>

      <SectionCard
        title="快捷入口"
        description="从原型页直接进入规划、执行和总结视图。"
      >
        <div className="project-nav-buttons">
          {(project.status === 'draft' || project.status === 'planning') && (
            <button className="btn btn-primary" onClick={() => navigate(`/projects/${id}/plan`)}>
              进入 Plan
            </button>
          )}
          {(project.status === 'executing' || project.status === 'planning' || project.status === 'completed') && (
            <button className="btn btn-primary" onClick={() => navigate(`/projects/${id}/tasks`)}>
              查看任务
            </button>
          )}
          {project.status === 'completed' && (
            <button className="btn btn-secondary" onClick={() => navigate(`/projects/${id}/summary`)}>
              查看总结
            </button>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
