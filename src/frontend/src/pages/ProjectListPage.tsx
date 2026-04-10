import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { isAdminUser } from '../auth';
import { Project } from '../types';
import StatusBadge from '../components/StatusBadge';

export default function ProjectListPage() {
  const isAdmin = isAdminUser();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  function fetchProjects() {
    setLoading(true);
    api.get<Project[]>('/api/projects')
      .then(setProjects)
      .catch(() => setError('加载项目失败。'))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchProjects();
  }, []);

  async function handleDelete(project: Project) {
    if (!confirm(`确认删除项目“${project.name}”吗？该操作会删除项目相关任务与计划。`)) return;
    setDeletingId(project.id);
    setError('');
    try {
      await api.delete(`/api/projects/${project.id}`);
      fetchProjects();
    } catch (err) {
      setError(`删除项目失败：${err}`);
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) return <div className="page-loading">正在加载项目...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1>项目</h1>
        <div className="header-actions">
          <Link to="/projects/new" className="btn btn-primary" title="创建一个新的项目并配置目标与 Agent">
            新建项目
          </Link>
          {isAdmin && (
            <Link to="/settings" className="btn btn-secondary" title="设置轮询间隔、启动延迟等全局参数">
              设置
            </Link>
          )}
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {projects.length === 0 ? (
        <div className="empty-state">
          <p>当前还没有项目，请先创建第一个项目。</p>
        </div>
      ) : (
        <div className="card-grid">
          {projects.map((project) => (
            <div key={project.id} className="project-card" title="点击卡片主体查看项目详情、Plan 和任务执行状态">
              <div className="project-card-header">
                <h3 onClick={() => navigate(`/projects/${project.id}`)}>{project.name}</h3>
                <StatusBadge status={project.status} />
              </div>
              <p className="project-card-goal" onClick={() => navigate(`/projects/${project.id}`)}>{project.goal}</p>
              <div className="project-card-footer">
                <span>{project.agent_ids?.length || 0} 个 Agent</span>
                <span className="created-at">{new Date(project.created_at).toLocaleDateString('zh-CN')}</span>
              </div>
              <div className="project-card-actions">
                <button className="btn btn-sm btn-ghost" onClick={() => navigate(`/projects/${project.id}/edit`)} title="编辑项目基础信息与 Agent 选择">
                  编辑
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(project)} disabled={deletingId === project.id} title="删除当前项目">
                  {deletingId === project.id ? '删除中...' : '删除'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
