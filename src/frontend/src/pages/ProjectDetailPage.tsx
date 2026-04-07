import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Project } from '../types';
import StatusBadge from '../components/StatusBadge';
import { getNextStepAction, getNextStepText } from '../contracts';

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchProject = useCallback(() => {
    api.get<Project>(`/api/projects/${id}`)
      .then(setProject)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    fetchProject();
  }, [fetchProject]);

  useEffect(() => {
    if (!project || !['planning', 'executing'].includes(project.status)) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      void fetchProject();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [fetchProject, project?.status]);

  if (loading) return <div className="page-loading">正在加载项目...</div>;
  if (!project) return <div className="page-loading">未找到该项目。</div>;

  const summary = project.task_summary;
  const nextStepText = getNextStepText(project.next_step);
  const nextStepAction = getNextStepAction(project.next_step);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{project.name}</h1>
          <StatusBadge status={project.status} />
        </div>
        <button className="btn btn-secondary" onClick={fetchProject} title="重新拉取项目状态、下一步提示和任务统计">
          手动刷新
        </button>
      </div>

      {nextStepText && (
        <div className="next-step-banner">
          <strong>下一步：</strong> {nextStepText}
          {nextStepAction && (
            <span className="next-step-action">（{nextStepAction}）</span>
          )}
        </div>
      )}

      <div className="project-detail-body">
        <div className="detail-section">
          <label>项目目标</label>
          <p>{project.goal}</p>
        </div>

        {project.git_repo_url && (
          <div className="detail-section">
            <label>仓库地址</label>
            <p>{project.git_repo_url}</p>
          </div>
        )}

        {project.collaboration_dir && (
          <div className="detail-section">
            <label>协作目录</label>
            <p>{project.collaboration_dir}</p>
          </div>
        )}

        {summary && (
          <div className="task-summary-grid">
            <div className="summary-card" title="项目中的全部任务数量">
              <span className="summary-number">{summary.total}</span>
              <span className="summary-label">总任务数</span>
            </div>
            <div className="summary-card" title="尚未开始执行的任务数量">
              <span className="summary-number" style={{ color: '#9ca3af' }}>{summary.pending}</span>
              <span className="summary-label">待处理</span>
            </div>
            <div className="summary-card" title="当前正在执行中的任务数量">
              <span className="summary-number" style={{ color: '#ef4444' }}>{summary.running}</span>
              <span className="summary-label">运行中</span>
            </div>
            <div className="summary-card" title="已经完成的任务数量">
              <span className="summary-number" style={{ color: '#22c55e' }}>{summary.completed}</span>
              <span className="summary-label">已完成</span>
            </div>
            <div className="summary-card" title="需要人工介入处理的任务数量">
              <span className="summary-number" style={{ color: '#eab308' }}>{summary.needs_attention}</span>
              <span className="summary-label">需关注</span>
            </div>
            <div className="summary-card" title="已被放弃的任务数量">
              <span className="summary-number" style={{ color: '#6b7280' }}>{summary.abandoned}</span>
              <span className="summary-label">已放弃</span>
            </div>
          </div>
        )}

        <div className="project-nav-buttons">
          {(project.status === 'draft' || project.status === 'planning') && (
            <button
              className="btn btn-primary"
              onClick={() => navigate(`/projects/${id}/plan`)}
              title="进入 Plan 页面，生成、导入并定稿项目 Plan"
            >
              进入 Plan
            </button>
          )}
          {(project.status === 'executing' || project.status === 'planning' || project.status === 'completed') && (
            <button
              className="btn btn-primary"
              onClick={() => navigate(`/projects/${id}/tasks`)}
              title="查看任务 DAG、任务详情和执行操作"
            >
              查看任务
            </button>
          )}
          {project.status === 'completed' && (
            <button
              className="btn btn-secondary"
              onClick={() => navigate(`/projects/${id}/summary`)}
              title="查看项目执行结果和人工干预记录"
            >
              查看总结
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
