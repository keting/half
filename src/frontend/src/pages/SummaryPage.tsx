import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Task, Agent, Project } from '../types';
import StatusBadge from '../components/StatusBadge';

interface SummaryEvent {
  id: number;
  task_id: number;
  event_type: string;
  detail: string | null;
  created_at: string;
}

interface SummaryTask extends Omit<Task, 'depends_on_json'> {
  depends_on: string[];
}

interface ProjectSummaryResponse {
  project_id: number;
  project_name: string;
  project_status: string;
  total_tasks: number;
  completed: number;
  running: number;
  pending: number;
  needs_attention: number;
  abandoned: number;
  tasks: SummaryTask[];
  events?: SummaryEvent[];
}

const EVENT_LABELS: Record<string, string> = {
  human_intervention: '人工干预',
  manual_complete: '人工完成',
  redispatched: '重新派发',
  abandoned: '已放弃',
};

export default function SummaryPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<SummaryTask[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [events, setEvents] = useState<SummaryEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [proj, summary, agentList] = await Promise.all([
        api.get<Project>(`/api/projects/${id}`),
        api.get<ProjectSummaryResponse>(`/api/projects/${id}/summary`),
        api.get<Agent[]>('/api/agents'),
      ]);
      setProject(proj);
      setTasks(summary.tasks);
      setAgents(agentList);
      setEvents(summary.events ?? []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const getAgentName = (agentId: number | null) => {
    if (agentId == null) {
      return '未分配';
    }
    const agent = agents.find((a) => a.id === agentId);
    return agent ? agent.name : `Agent #${agentId}`;
  };

  const humanEvents = events.filter(
    (e) =>
      e.event_type === 'human_intervention' ||
      e.event_type === 'manual_complete' ||
      e.event_type === 'redispatched' ||
      e.event_type === 'abandoned'
  );

  if (loading) return <div className="page-loading">正在加载总结...</div>;
  if (!project) return <div className="page-loading">未找到该项目。</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1>执行总结</h1>
        <button className="btn btn-ghost" onClick={() => navigate(`/projects/${id}`)} title="返回项目详情页">
          返回项目
        </button>
      </div>

      <div className="summary-result">
        <h3>项目：{project.name}</h3>
        <StatusBadge status={project.status} />
        <p className="summary-goal">{project.goal}</p>
      </div>

      <div className="summary-table-section">
        <h3>任务结果</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>编号</th>
              <th>名称</th>
              <th>状态</th>
              <th>Agent</th>
              <th>输出文件</th>
              <th>完成时间</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td className="code-cell">{task.task_code}</td>
                <td>{task.task_name}</td>
                <td><StatusBadge status={task.status} /></td>
                <td>{getAgentName(task.assignee_agent_id)}</td>
                <td>
                  {task.result_file_path ? (
                    <span
                      className="file-link file-link-copy"
                      title="点击复制路径"
                      onClick={() => navigator.clipboard?.writeText(task.result_file_path!)}
                    >
                      {task.result_file_path}
                    </span>
                  ) : (
                    <span className="text-muted">-</span>
                  )}
                </td>
                <td>
                  {task.completed_at
                    ? new Date(task.completed_at).toLocaleString('zh-CN')
                    : <span className="text-muted">-</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {humanEvents.length > 0 && (
        <div className="summary-table-section">
          <h3>人工干预记录</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>事件类型</th>
                <th>详情</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {humanEvents.map((event) => {
                const task = tasks.find((t) => t.id === event.task_id);
                return (
                  <tr key={event.id}>
                    <td className="code-cell">{task ? task.task_code : `#${event.task_id}`}</td>
                    <td>{EVENT_LABELS[event.event_type] || event.event_type}</td>
                    <td>{event.detail || '-'}</td>
                    <td>{new Date(event.created_at).toLocaleString('zh-CN')}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
