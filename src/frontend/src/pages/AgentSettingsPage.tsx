import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { isAdminUser } from '../auth';
import { AgentTypeConfig, ModelDefinition } from '../types';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';

export default function AgentSettingsPage() {
  const navigate = useNavigate();
  const isAdmin = isAdminUser();
  const [types, setTypes] = useState<AgentTypeConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Agent type form
  const [newTypeName, setNewTypeName] = useState('');
  const [editingTypeId, setEditingTypeId] = useState<number | null>(null);
  const [editingTypeName, setEditingTypeName] = useState('');
  const [typeSuggestions, setTypeSuggestions] = useState<{ id: number; name: string }[]>([]);
  const [showTypeSuggestions, setShowTypeSuggestions] = useState(false);
  const typeSuggestionsRef = useRef<HTMLDivElement>(null);

  // Agent type description editing
  const [editingDescTypeId, setEditingDescTypeId] = useState<number | null>(null);
  const [editingDesc, setEditingDesc] = useState('');

  // Model form
  const [addingModelTypeId, setAddingModelTypeId] = useState<number | null>(null);
  const [newModelName, setNewModelName] = useState('');
  const [modelSuggestions, setModelSuggestions] = useState<ModelDefinition[]>([]);
  const [showModelSuggestions, setShowModelSuggestions] = useState(false);
  const modelSuggestionsRef = useRef<HTMLDivElement>(null);

  // Model editing
  const [editingModelId, setEditingModelId] = useState<number | null>(null);
  const [editModelForm, setEditModelForm] = useState({ name: '', alias: '', capability: '' });

  // Drag state for types
  const [draggedTypeId, setDraggedTypeId] = useState<number | null>(null);
  const [dragOverTypeId, setDragOverTypeId] = useState<number | null>(null);

  // Drag state for models (scoped per type)
  const [draggedModelId, setDraggedModelId] = useState<number | null>(null);
  const [dragOverModelId, setDragOverModelId] = useState<number | null>(null);
  const [dragModelTypeId, setDragModelTypeId] = useState<number | null>(null);

  const fetchTypes = useCallback(() => {
    api.get<AgentTypeConfig[]>('/api/agent-settings/types')
      .then(setTypes)
      .catch(() => setError('加载失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!isAdmin) {
      navigate('/agents', { replace: true });
      return;
    }
    fetchTypes();
  }, [fetchTypes, isAdmin, navigate]);

  // Click-outside for suggestions
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (typeSuggestionsRef.current && !typeSuggestionsRef.current.contains(e.target as Node)) {
        setShowTypeSuggestions(false);
      }
      if (modelSuggestionsRef.current && !modelSuggestionsRef.current.contains(e.target as Node)) {
        setShowModelSuggestions(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  // --- Agent Type auto-complete ---
  async function handleTypeNameInput(value: string) {
    setNewTypeName(value);
    if (value.trim().length > 0) {
      try {
        const results = await api.get<{ id: number; name: string }[]>(`/api/agent-settings/types/search?q=${encodeURIComponent(value)}`);
        setTypeSuggestions(results);
        setShowTypeSuggestions(results.length > 0);
      } catch { setShowTypeSuggestions(false); }
    } else {
      setShowTypeSuggestions(false);
    }
  }

  async function handleAddType() {
    const name = newTypeName.trim();
    if (!name) return;
    setError('');
    try {
      await api.post('/api/agent-settings/types', { name });
      setNewTypeName('');
      setShowTypeSuggestions(false);
      fetchTypes();
    } catch (err) { setError(`添加失败：${err}`); }
  }

  async function handleUpdateType(typeId: number) {
    const name = editingTypeName.trim();
    if (!name) return;
    setError('');
    try {
      await api.put(`/api/agent-settings/types/${typeId}`, { name });
      setEditingTypeId(null);
      fetchTypes();
    } catch (err) { setError(`更新失败：${err}`); }
  }

  async function handleSaveDescription(typeId: number) {
    setError('');
    try {
      await api.put(`/api/agent-settings/types/${typeId}`, { description: editingDesc.trim() || null });
      setEditingDescTypeId(null);
      fetchTypes();
    } catch (err) { setError(`保存介绍失败：${err}`); }
  }

  async function handleDeleteType(typeId: number, typeName: string) {
    if (!confirm(`确认删除 Agent 类型 "${typeName}" 吗？`)) return;
    setError('');
    try {
      await api.delete(`/api/agent-settings/types/${typeId}`);
      fetchTypes();
    } catch (err) { setError(`删除失败：${err}`); }
  }

  // --- Model auto-complete ---
  async function handleModelNameInput(value: string) {
    setNewModelName(value);
    if (value.trim().length > 0) {
      try {
        const results = await api.get<ModelDefinition[]>(`/api/agent-settings/models/search?q=${encodeURIComponent(value)}`);
        setModelSuggestions(results);
        setShowModelSuggestions(results.length > 0);
      } catch { setShowModelSuggestions(false); }
    } else {
      setShowModelSuggestions(false);
    }
  }

  async function handleAddModel(typeId: number) {
    const name = newModelName.trim();
    if (!name) return;
    setError('');
    try {
      await api.post(`/api/agent-settings/types/${typeId}/models`, { name });
      setNewModelName('');
      setAddingModelTypeId(null);
      setShowModelSuggestions(false);
      fetchTypes();
    } catch (err) { setError(`添加模型失败：${err}`); }
  }

  async function handleRemoveModel(typeId: number, modelId: number, modelName: string) {
    if (!confirm(`确认从该类型中移除模型 "${modelName}" 吗？`)) return;
    setError('');
    try {
      await api.delete(`/api/agent-settings/types/${typeId}/models/${modelId}`);
      fetchTypes();
    } catch (err) { setError(`移除失败：${err}`); }
  }

  function startEditModel(model: ModelDefinition) {
    setEditingModelId(model.id);
    setEditModelForm({
      name: model.name,
      alias: model.alias || '',
      capability: model.capability || '',
    });
  }

  async function handleSaveModel() {
    if (!editingModelId) return;
    setError('');
    try {
      await api.put(`/api/agent-settings/models/${editingModelId}`, {
        name: editModelForm.name.trim() || undefined,
        alias: editModelForm.alias.trim() || null,
        capability: editModelForm.capability.trim() || null,
      });
      setEditingModelId(null);
      fetchTypes();
    } catch (err) { setError(`保存失败：${err}`); }
  }

  async function handleReorderTypes(fromId: number, toId: number) {
    if (fromId === toId) return;
    const ordered = [...types];
    const fromIndex = ordered.findIndex((t) => t.id === fromId);
    const toIndex = ordered.findIndex((t) => t.id === toId);
    if (fromIndex === -1 || toIndex === -1) return;
    const [moved] = ordered.splice(fromIndex, 1);
    ordered.splice(toIndex, 0, moved);
    setTypes(ordered);
    try {
      const result = await api.put<AgentTypeConfig[]>('/api/agent-settings/types/reorder', { type_ids: ordered.map((t) => t.id) });
      setTypes(result);
    } catch { fetchTypes(); }
  }

  async function handleReorderModels(typeId: number, fromModelId: number, toModelId: number) {
    if (fromModelId === toModelId) return;
    const typeIndex = types.findIndex((t) => t.id === typeId);
    if (typeIndex === -1) return;
    const models = [...types[typeIndex].models];
    const fromIndex = models.findIndex((m) => m.id === fromModelId);
    const toIndex = models.findIndex((m) => m.id === toModelId);
    if (fromIndex === -1 || toIndex === -1) return;
    const [moved] = models.splice(fromIndex, 1);
    models.splice(toIndex, 0, moved);
    // Optimistic update
    const updatedTypes = [...types];
    updatedTypes[typeIndex] = { ...updatedTypes[typeIndex], models };
    setTypes(updatedTypes);
    try {
      const result = await api.put<AgentTypeConfig>(`/api/agent-settings/types/${typeId}/models/reorder`, { model_ids: models.map((m) => m.id) });
      setTypes((prev) => prev.map((t) => t.id === typeId ? result : t));
    } catch { fetchTypes(); }
  }

  if (loading) return <div className="page-loading">正在加载设置...</div>;

  return (
    <div className="page">
      <PageHeader title="智能体设置" description="管理 Agent 类型与模型配置">
        <button className="btn btn-ghost" onClick={() => navigate('/agents')}>返回智能体</button>
      </PageHeader>

      {error && <div className="error-message">{error}</div>}

      {/* Add new agent type */}
      <SectionCard title="Agent 类型管理" description="配置可用的 Agent 类型和每个类型下的模型">
        <div className="settings-add-row">
          <div className="settings-autocomplete-container" ref={typeSuggestionsRef}>
            <input
              type="text"
              value={newTypeName}
              onChange={(e) => handleTypeNameInput(e.target.value)}
              onFocus={() => newTypeName.trim() && handleTypeNameInput(newTypeName)}
              placeholder="输入新 Agent 类型名称"
              className="settings-input"
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddType(); } }}
            />
            {showTypeSuggestions && typeSuggestions.length > 0 && (
              <div className="settings-suggestions">
                {typeSuggestions.map((s) => (
                  <div
                    key={s.id}
                    className="settings-suggestion-item"
                    onClick={() => { setNewTypeName(s.name); setShowTypeSuggestions(false); }}
                  >
                    {s.name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button className="btn btn-primary btn-sm" onClick={handleAddType} disabled={!newTypeName.trim()}>
            添加类型
          </button>
        </div>
      </SectionCard>

      {/* Agent type list */}
      <div className="settings-type-list">
        {types.map((agentType) => (
          <div
            key={agentType.id}
            className={`settings-type-drag-wrapper${draggedTypeId === agentType.id ? ' settings-type-dragging' : ''}${dragOverTypeId === agentType.id ? ' settings-type-dragover' : ''}`}
            draggable
            onDragStart={(e) => {
              setDraggedTypeId(agentType.id);
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', `type-${agentType.id}`);
            }}
            onDragEnd={() => { setDraggedTypeId(null); setDragOverTypeId(null); }}
            onDragOver={(e) => {
              const data = e.dataTransfer.types.includes('text/plain');
              if (!data || draggedModelId != null) return;
              e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragOverTypeId(agentType.id);
            }}
            onDragLeave={() => { if (dragOverTypeId === agentType.id) setDragOverTypeId(null); }}
            onDrop={(e) => {
              if (draggedModelId != null) return;
              e.preventDefault();
              setDragOverTypeId(null);
              if (draggedTypeId != null && draggedTypeId !== agentType.id) {
                handleReorderTypes(draggedTypeId, agentType.id);
              }
              setDraggedTypeId(null);
            }}
          >
          <SectionCard title="">
            <div className="settings-type-header">
              <span className="agent-card-drag-handle" title="拖动排序">⠿</span>
              {editingTypeId === agentType.id ? (
                <div className="settings-edit-row" style={{ flex: 1 }}>
                  <input
                    type="text"
                    value={editingTypeName}
                    onChange={(e) => setEditingTypeName(e.target.value)}
                    className="settings-input"
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleUpdateType(agentType.id); } }}
                    autoFocus
                  />
                  <button className="btn btn-primary btn-sm" onClick={() => handleUpdateType(agentType.id)}>保存</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setEditingTypeId(null)}>取消</button>
                </div>
              ) : (
                <>
                  <h3 className="settings-type-name" style={{ flex: 1 }}>{agentType.name}</h3>
                  <div className="settings-type-actions">
                    <button
                      className="btn btn-sm btn-edit"
                      onClick={() => { setEditingTypeId(agentType.id); setEditingTypeName(agentType.name); }}
                    >
                      编辑
                    </button>
                    <button
                      className="btn btn-sm btn-delete"
                      onClick={() => handleDeleteType(agentType.id, agentType.name)}
                    >
                      删除
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* Agent description */}
            <div className="settings-type-desc">
              {editingDescTypeId === agentType.id ? (
                <div className="settings-desc-edit">
                  <textarea
                    value={editingDesc}
                    onChange={(e) => setEditingDesc(e.target.value)}
                    rows={3}
                    placeholder="介绍该智能体的能力、使用限制等，如：1M Context、速度更快、支持长文本分析等"
                    autoFocus
                  />
                  <div className="settings-desc-edit-actions">
                    <button className="btn btn-primary btn-sm" onClick={() => handleSaveDescription(agentType.id)}>保存</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditingDescTypeId(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <div className="settings-desc-display" onClick={() => { setEditingDescTypeId(agentType.id); setEditingDesc(agentType.description || ''); }}>
                  {agentType.description
                    ? <p className="settings-desc-text">{agentType.description}</p>
                    : <p className="settings-desc-placeholder">点击添加 Agent 介绍...</p>
                  }
                </div>
              )}
            </div>

            {/* Models list */}
            <div className="settings-models-list">
              {agentType.models.map((model) => (
                <div
                  key={model.id}
                  className={`settings-model-item${draggedModelId === model.id ? ' settings-model-dragging' : ''}${dragOverModelId === model.id ? ' settings-model-dragover' : ''}`}
                  draggable
                  onDragStart={(e) => {
                    e.stopPropagation();
                    setDraggedModelId(model.id);
                    setDragModelTypeId(agentType.id);
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/plain', `model-${model.id}`);
                  }}
                  onDragEnd={() => { setDraggedModelId(null); setDragOverModelId(null); setDragModelTypeId(null); }}
                  onDragOver={(e) => {
                    if (draggedModelId == null || dragModelTypeId !== agentType.id) return;
                    e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = 'move'; setDragOverModelId(model.id);
                  }}
                  onDragLeave={() => { if (dragOverModelId === model.id) setDragOverModelId(null); }}
                  onDrop={(e) => {
                    if (draggedModelId == null || dragModelTypeId !== agentType.id) return;
                    e.preventDefault(); e.stopPropagation();
                    setDragOverModelId(null);
                    if (draggedModelId !== model.id) {
                      handleReorderModels(agentType.id, draggedModelId, model.id);
                    }
                    setDraggedModelId(null); setDragModelTypeId(null);
                  }}
                >
                  {editingModelId === model.id ? (
                    <div className="settings-model-edit">
                      <div className="form-row">
                        <div className="form-group">
                          <label>模型名称</label>
                          <input
                            type="text"
                            value={editModelForm.name}
                            onChange={(e) => setEditModelForm((prev) => ({ ...prev, name: e.target.value }))}
                          />
                        </div>
                        <div className="form-group">
                          <label>别名</label>
                          <input
                            type="text"
                            value={editModelForm.alias}
                            onChange={(e) => setEditModelForm((prev) => ({ ...prev, alias: e.target.value }))}
                            placeholder="可选"
                          />
                        </div>
                      </div>
                      <div className="form-group">
                        <label>能力描述 <span className="helper-text">({editModelForm.capability.length}/150)</span></label>
                        <textarea
                          value={editModelForm.capability}
                          onChange={(e) => setEditModelForm((prev) => ({ ...prev, capability: e.target.value.slice(0, 150) }))}
                          rows={2}
                          maxLength={150}
                          placeholder="描述该模型擅长的能力、适合的任务场景、性价比等"
                        />
                      </div>
                      <div className="settings-model-edit-actions">
                        <button className="btn btn-primary btn-sm" onClick={handleSaveModel}>保存</button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditingModelId(null)}>取消</button>
                      </div>
                    </div>
                  ) : (
                    <div className="settings-model-row">
                      <span className="agent-card-drag-handle settings-model-drag-handle" title="拖动排序">⠿</span>
                      <div className="settings-model-info">
                        <span className="settings-model-name">{model.name}</span>
                        {model.alias && <span className="settings-model-alias">({model.alias})</span>}
                        {model.capability && <span className="settings-model-capability">{model.capability}</span>}
                        {!model.capability && <span className="settings-model-no-capability">未设置能力描述</span>}
                      </div>
                      <div className="settings-model-actions">
                        <button className="btn btn-xs btn-outline" onClick={() => startEditModel(model)}>编辑</button>
                        <button className="btn btn-xs btn-outline btn-danger-text" onClick={() => handleRemoveModel(agentType.id, model.id, model.name)}>移除</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {/* Add model */}
              {addingModelTypeId === agentType.id ? (
                <div className="settings-add-model-row" ref={modelSuggestionsRef}>
                  <div className="settings-autocomplete-container">
                    <input
                      type="text"
                      value={newModelName}
                      onChange={(e) => handleModelNameInput(e.target.value)}
                      onFocus={() => newModelName.trim() && handleModelNameInput(newModelName)}
                      placeholder="输入模型名称"
                      className="settings-input"
                      autoFocus
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddModel(agentType.id); } }}
                    />
                    {showModelSuggestions && modelSuggestions.length > 0 && (
                      <div className="settings-suggestions">
                        {modelSuggestions.map((s) => (
                          <div
                            key={s.id}
                            className="settings-suggestion-item"
                            onClick={() => { setNewModelName(s.name); setShowModelSuggestions(false); }}
                          >
                            <span>{s.name}</span>
                            {s.alias && <span className="settings-suggestion-alias">({s.alias})</span>}
                            {s.capability && <span className="settings-suggestion-cap">{s.capability}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <button className="btn btn-primary btn-sm" onClick={() => handleAddModel(agentType.id)} disabled={!newModelName.trim()}>确定</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => { setAddingModelTypeId(null); setNewModelName(''); setShowModelSuggestions(false); }}>取消</button>
                </div>
              ) : (
                <button
                  className="btn btn-secondary btn-sm settings-add-model-btn"
                  onClick={() => { setAddingModelTypeId(agentType.id); setNewModelName(''); }}
                >
                  添加模型
                </button>
              )}
            </div>
          </SectionCard>
          </div>
        ))}

        {types.length === 0 && (
          <div className="empty-state">还没有配置任何 Agent 类型。</div>
        )}
      </div>
    </div>
  );
}
