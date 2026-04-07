import React, { useEffect, useMemo, useState } from 'react';
import { Task, Agent } from '../types';
import { api } from '../api/client';
import StatusBadge from './StatusBadge';
import { copyTaskPromptAndDispatch } from '../contracts';

interface Props {
  task: Task;
  agents: Agent[];
  allTasks: Task[];
  onRefresh: () => void;
}

export default function TaskDetailPanel({ task, agents, allTasks, onRefresh }: Props) {
  const [loading, setLoading] = useState('');
  const [copied, setCopied] = useState(false);
  const [showDispatchReminder, setShowDispatchReminder] = useState(false);
  const dispatchReminderRef = React.useRef<number | null>(null);
  const [draftTaskName, setDraftTaskName] = useState(task.task_name);
  const [draftDescription, setDraftDescription] = useState(task.description || '');
  const [draftExpectedOutput, setDraftExpectedOutput] = useState(task.expected_output_path || '');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const assignee = agents.find((a) => a.id === task.assignee_agent_id);

  let deps: string[] = [];
  try {
    deps = JSON.parse(task.depends_on_json || '[]');
  } catch {
    deps = [];
  }

  const predecessorTasks = allTasks.filter((t) => deps.includes(t.task_code));
  const blockedPredecessors = predecessorTasks.filter(
    (predecessorTask) => predecessorTask.status !== 'completed' && predecessorTask.status !== 'abandoned'
  );
  const canOperate = blockedPredecessors.length === 0;
  const canEdit = task.status === 'pending' && canOperate;

  useEffect(() => {
    setDraftTaskName(task.task_name);
    setDraftDescription(task.description || '');
    setDraftExpectedOutput(task.expected_output_path || '');
    setSaveState('idle');
  }, [task.description, task.expected_output_path, task.id, task.task_name]);

  const normalizedDraft = useMemo(() => ({
    task_name: draftTaskName.trim(),
    description: draftDescription,
    expected_output_path: draftExpectedOutput,
  }), [draftDescription, draftExpectedOutput, draftTaskName]);

  useEffect(() => {
    if (!canEdit) return undefined;
    if (
      normalizedDraft.task_name === task.task_name
      && normalizedDraft.description === (task.description || '')
      && normalizedDraft.expected_output_path === (task.expected_output_path || '')
    ) {
      return undefined;
    }

    setSaveState('saving');
    const timer = window.setTimeout(async () => {
      try {
        await api.put(`/api/tasks/${task.id}`, normalizedDraft);
        setSaveState('saved');
        onRefresh();
      } catch {
        setSaveState('error');
      }
    }, 600);

    return () => window.clearTimeout(timer);
  }, [canEdit, normalizedDraft, onRefresh, task.description, task.expected_output_path, task.id, task.task_name]);

  useEffect(() => {
    if (saveState !== 'saved') return undefined;
    const timer = window.setTimeout(() => setSaveState('idle'), 1200);
    return () => window.clearTimeout(timer);
  }, [saveState]);

  async function handleCopyPrompt() {
    if (!canOperate) {
      alert(`前序任务尚未全部完成，无法派发：${blockedPredecessors.map((taskItem) => taskItem.task_code).join(', ')}`);
      return;
    }
    setLoading('dispatch');
    try {
      await copyTaskPromptAndDispatch(api, navigator.clipboard, task.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      setShowDispatchReminder(false);
      if (dispatchReminderRef.current) clearTimeout(dispatchReminderRef.current);
      dispatchReminderRef.current = window.setTimeout(() => setShowDispatchReminder(true), 5 * 60 * 1000);
      onRefresh();
    } catch (err) {
      alert(`派发失败：${err}`);
    } finally {
      setLoading('');
    }
  }

  async function handleRedispatch() {
    setLoading('redispatch');
    try {
      await api.post(`/api/tasks/${task.id}/redispatch`);
      onRefresh();
    } catch (err) {
      alert(`重新派发失败：${err}`);
    } finally {
      setLoading('');
    }
  }

  async function handleMarkComplete() {
    setLoading('complete');
    try {
      await api.post(`/api/tasks/${task.id}/mark-complete`);
      onRefresh();
    } catch (err) {
      alert(`手动完成失败：${err}`);
    } finally {
      setLoading('');
    }
  }

  async function handleAbandon() {
    if (!canOperate) {
      alert(`前序任务尚未全部完成，当前不能放弃：${blockedPredecessors.map((taskItem) => taskItem.task_code).join(', ')}`);
      return;
    }
    if (!confirm('确认放弃这个任务吗？该操作会记录为人工干预。')) return;
    setLoading('abandon');
    try {
      await api.post(`/api/tasks/${task.id}/abandon`);
      onRefresh();
    } catch (err) {
      alert(`放弃任务失败：${err}`);
    } finally {
      setLoading('');
    }
  }

  return (
    <div className="task-detail-panel">
      <h3>{task.task_code}: {task.task_name}</h3>
      <StatusBadge status={task.status} />

      <div className="detail-section">
        <label>指派 Agent</label>
        <p>{assignee ? `${assignee.name} (${assignee.agent_type}${assignee.model_name ? ` / ${assignee.model_name}` : ''})` : (task.assignee_agent_id ? `Agent #${task.assignee_agent_id}` : '未指派')}</p>
      </div>

      <div className="detail-section">
        <label>前置依赖</label>
        {predecessorTasks.length === 0 ? (
          <p>无</p>
        ) : (
          <ul className="dep-list">
            {predecessorTasks.map((pt) => (
              <li key={pt.id}>
                <span className="dep-code">{pt.task_code}</span> - {pt.task_name}
                {pt.result_file_path && (
                  <span className="dep-output">（输出文件：{pt.result_file_path}）</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="detail-section">
        <label>任务名称</label>
        {canEdit ? (
          <input
            value={draftTaskName}
            onChange={(event) => setDraftTaskName(event.target.value)}
            className="detail-input"
            placeholder="请输入任务名称"
          />
        ) : (
          <p>{task.task_name}</p>
        )}
      </div>

      <div className="detail-section">
        <label>任务描述</label>
        {canEdit ? (
          <textarea
            value={draftDescription}
            onChange={(event) => setDraftDescription(event.target.value)}
            rows={5}
            className="detail-textarea"
            placeholder="请输入任务描述"
          />
        ) : (
          <p>{task.description || '暂无描述'}</p>
        )}
      </div>

      <div className="detail-section">
        <label>预期输出</label>
        {canEdit ? (
          <textarea
            value={draftExpectedOutput}
            onChange={(event) => setDraftExpectedOutput(event.target.value)}
            rows={3}
            className="detail-textarea"
            placeholder="请输入预期输出"
          />
        ) : (
          <p>{task.expected_output_path || '暂无描述'}</p>
        )}
      </div>

      {canEdit && (
        <div className={`helper-text ${saveState === 'error' ? 'helper-text-error' : ''}`}>
          {saveState === 'saving' && '正在自动保存...'}
          {saveState === 'saved' && '已自动保存'}
          {saveState === 'error' && '自动保存失败，请稍后重试'}
          {saveState === 'idle' && '修改右侧文本后会自动保存'}
        </div>
      )}

      {task.result_file_path && (
        <div className="detail-section">
          <label>结果文件</label>
          <p>{task.result_file_path}</p>
        </div>
      )}

      {task.last_error && (
        <div className="detail-section error-section">
          <label>最近错误</label>
          <p className="error-text">{task.last_error}</p>
        </div>
      )}

      <div className="detail-section">
        <label>超时时间</label>
        <p>{task.timeout_minutes} 分钟</p>
      </div>

      {task.dispatched_at && (
        <div className="detail-section">
          <label>派发时间</label>
          <p>{new Date(task.dispatched_at).toLocaleString('zh-CN')}</p>
        </div>
      )}

      {task.completed_at && (
        <div className="detail-section">
          <label>完成时间</label>
          <p>{new Date(task.completed_at).toLocaleString('zh-CN')}</p>
        </div>
      )}

      <div className="detail-actions">
        {(task.status === 'pending' || task.status === 'needs_attention') && (
          <div className="copy-prompt-row">
            <button
              className="btn btn-primary"
              onClick={handleCopyPrompt}
              disabled={loading === 'dispatch' || !canOperate}
              title="生成当前任务的 Prompt，复制到剪贴板，并同步派发任务"
            >
              {copied ? 'Prompt 已复制' : '复制 Prompt 并派发'}
            </button>
          </div>
        )}

        {showDispatchReminder && task.status === 'running' && (
          <div className="helper-text helper-text-warning">
            已超过 5 分钟未检测到 Git 变更，是否已将 Prompt 发送给 Agent？
          </div>
        )}

        {!canOperate && (task.status === 'pending' || task.status === 'needs_attention') && (
          <div className="helper-text helper-text-error">
            前序任务未全部完成，当前不能复制 Prompt 或放弃任务。
          </div>
        )}

        {(task.status === 'running' || task.status === 'needs_attention') && (
          <button
            className="btn btn-secondary"
            onClick={handleRedispatch}
            disabled={loading === 'redispatch'}
            title="将当前任务重新派发给对应 Agent"
          >
            重新派发
          </button>
        )}

        {(task.status === 'running' || task.status === 'needs_attention') && (
          <button
            className="btn btn-success"
            onClick={handleMarkComplete}
            disabled={loading === 'complete'}
            title="在人工确认结果无误后，手动将任务标记为完成"
          >
            标记完成
          </button>
        )}

        {task.status !== 'completed' && task.status !== 'abandoned' && (
          <button
            className="btn btn-danger"
            onClick={handleAbandon}
            disabled={loading === 'abandon' || !canOperate}
            title="放弃当前任务，并在系统中记录人工干预"
          >
            放弃任务
          </button>
        )}
      </div>
    </div>
  );
}
