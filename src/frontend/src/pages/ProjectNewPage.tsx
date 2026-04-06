import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { Agent, Project } from '../types';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';
import StatusBadge from '../components/StatusBadge';
import ModelBadge from '../components/ModelBadge';
import { deriveAgentStatus, getAgentModels, summarizeAgentCapabilities } from '../utils/agents';

export default function ProjectNewPage() {
  const { id } = useParams<{ id: string }>();
  const isEditMode = Boolean(id);
  const [name, setName] = useState('');
  const [goal, setGoal] = useState('');
  const [gitRepoUrl, setGitRepoUrl] = useState('');
  const [collaborationDir, setCollaborationDir] = useState('');
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const hasAgents = agents.length > 0;
  const canSubmit = hasAgents && selectedAgentIds.length > 0 && name.trim() && goal.trim() && !loading;
  const pageTitle = isEditMode ? '编辑项目' : '新建项目';

  useEffect(() => {
    async function fetchData() {
      try {
        const [agentList, project] = await Promise.all([
          api.get<Agent[]>('/api/agents'),
          isEditMode ? api.get<Project>(`/api/projects/${id}`) : Promise.resolve(null),
        ]);
        setAgents(agentList);
        if (project) {
          setName(project.name || '');
          setGoal(project.goal || '');
          setGitRepoUrl(project.git_repo_url || '');
          setCollaborationDir(project.collaboration_dir || '');
          setSelectedAgentIds(project.agent_ids || []);
        }
      } catch (err) {
        setError(`加载失败：${err}`);
      } finally {
        setInitializing(false);
      }
    }
    fetchData();
  }, [id, isEditMode]);

  const sortedAgents = useMemo(() => [...agents].sort((a, b) => a.name.localeCompare(b.name)), [agents]);

  function toggleAgent(agentId: number) {
    setSelectedAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((i) => i !== agentId) : [...prev, agentId]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!hasAgents) { setError('当前系统还没有 Agent，请先到智能体页面新增。'); return; }
    if (selectedAgentIds.length === 0) { setError('请至少选择 1 个 Agent。'); return; }
    setLoading(true);
    try {
      const payload = { name, goal, git_repo_url: gitRepoUrl, collaboration_dir: collaborationDir, agent_ids: selectedAgentIds };
      const project = isEditMode
        ? await api.put<Project>(`/api/projects/${id}`, payload)
        : await api.post<Project>('/api/projects', payload);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(`${isEditMode ? '更新' : '创建'}失败：${err}`);
    } finally { setLoading(false); }
  }

  if (initializing) return <div className="page-loading">正在加载...</div>;

  return (
    <div className="page page-narrow">
      <PageHeader title={pageTitle} />

      {!hasAgents && (
        <div className="empty-state compact-empty-state">
          <p>当前系统还没有注册 Agent，请先到智能体页面新增。</p>
          <Link to="/agents" className="btn btn-primary">前往智能体页面</Link>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <SectionCard title="项目信息">
          <div className="form-group">
            <label htmlFor="name">项目名称</label>
            <input id="name" type="text" value={name} onChange={(e) => setName(e.target.value)} required placeholder="例如：企业知识库助手" />
          </div>
          <div className="form-group">
            <label htmlFor="goal">项目目标</label>
            <textarea id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} required rows={4} placeholder="描述项目要完成什么、交付什么，以及验收标准。" />
          </div>
        </SectionCard>

        <SectionCard title="仓库配置" description="关联 Git 仓库用于多 Agent 协作">
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="repo">Git 仓库地址</label>
              <input id="repo" type="text" value={gitRepoUrl} onChange={(e) => setGitRepoUrl(e.target.value)} placeholder="例如：git@github.com:org/repo.git" className="input-mono" />
            </div>
            <div className="form-group">
              <label htmlFor="collab-dir">协作目录</label>
              <input id="collab-dir" type="text" value={collaborationDir} onChange={(e) => setCollaborationDir(e.target.value)} placeholder="留空则使用仓库根目录" className="input-mono" />
            </div>
          </div>
        </SectionCard>

        <SectionCard title="参与智能体" description="选择可参与此项目执行的 Agent">
          <div className="agent-select-cards">
            {sortedAgents.map((agent) => {
              const selected = selectedAgentIds.includes(agent.id);
              return (
                <div
                  key={agent.id}
                  className={`agent-select-card ${selected ? 'selected' : ''}`}
                  onClick={() => toggleAgent(agent.id)}
                >
                  <div className="agent-select-card-check">
                    <span className={`check-indicator ${selected ? 'checked' : ''}`} />
                  </div>
                  <div className="agent-select-card-body">
                    <div className="agent-select-card-top">
                      <span className="agent-select-card-name">{agent.name}</span>
                      <StatusBadge status={deriveAgentStatus(agent).status} />
                    </div>
                    <div className="agent-select-card-models">
                      {getAgentModels(agent).map((model, index) => (
                        <ModelBadge key={`${agent.id}-${model.model_name}-${index}`} type={index === 0 ? agent.agent_type : undefined} model={model.model_name} />
                      ))}
                    </div>
                    {summarizeAgentCapabilities(agent) && (
                      <p className="agent-select-card-cap">{summarizeAgentCapabilities(agent)}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {hasAgents && selectedAgentIds.length === 0 && (
            <div className="helper-text helper-text-error">请至少选择 1 个 Agent。</div>
          )}
        </SectionCard>

        {error && <div className="error-message">{error}</div>}

        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>取消</button>
          <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
            {loading ? (isEditMode ? '更新中...' : '创建中...') : (isEditMode ? '更新项目' : '创建项目')}
          </button>
        </div>
      </form>
    </div>
  );
}
