import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { isAdminUser } from '../auth';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';

interface PollingSettings {
  polling_interval_min: number;
  polling_interval_max: number;
  polling_start_delay_minutes: number;
  polling_start_delay_seconds: number;
}

export default function ProjectSettingsPage() {
  const navigate = useNavigate();
  const isAdmin = isAdminUser();
  const [settings, setSettings] = useState<PollingSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isAdmin) {
      navigate('/projects', { replace: true });
      return;
    }
    fetchSettings();
  }, [isAdmin, navigate]);

  function fetchSettings() {
    setLoading(true);
    api.get<PollingSettings>('/api/settings/polling')
      .then(setSettings)
      .catch(() => setError('加载设置失败'))
      .finally(() => setLoading(false));
  }

  function validateSettings(s: PollingSettings): string | null {
    if (s.polling_interval_min < 1 || s.polling_interval_min > 600) {
      return '轮询间隔最小值必须在 1-600 秒之间';
    }
    if (s.polling_interval_max < 1 || s.polling_interval_max > 600) {
      return '轮询间隔最大值必须在 1-600 秒之间';
    }
    if (s.polling_interval_min > s.polling_interval_max) {
      return '轮询间隔最小值不得大于最大值';
    }
    if (s.polling_start_delay_minutes < 0 || s.polling_start_delay_minutes > 60) {
      return '启动延迟分钟数必须在 0-60 之间';
    }
    if (s.polling_start_delay_seconds < 0 || s.polling_start_delay_seconds > 59) {
      return '启动延迟秒数必须在 0-59 之间';
    }
    return null;
  }

  async function handleSave() {
    if (!settings) return;

    const validationError = validateSettings(settings);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      await api.put('/api/settings/polling', settings);
      setSuccess('设置保存成功');
      setTimeout(() => setSuccess(''), 3000);
    } catch (err) {
      setError(`保存失败：${err}`);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="page-loading">正在加载设置...</div>;
  }

  if (!settings) {
    return (
      <div className="page">
        <PageHeader title="项目参数设置" />
        <div className="error-message">加载设置失败，请刷新重试</div>
      </div>
    );
  }

  return (
    <div className="page">
      <PageHeader title="项目参数设置" />

      {error && <div className="error-message">{error}</div>}
      {success && <div className="success-message">{success}</div>}

      <SectionCard title="轮询默认间隔">
        <p className="section-description">
          系统会在该范围内随机选择一个间隔时间进行轮询。例如，设置为 15-30 秒时，每次轮询会随机延迟 15-30 秒后再进行下一次轮询。这样可以避免规律性的轮询对服务器造成压力。
        </p>
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="interval_min">最小间隔（秒）</label>
            <input
              id="interval_min"
              type="number"
              min="1"
              max="600"
              value={settings.polling_interval_min}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  polling_interval_min: parseInt(e.target.value) || 15,
                })
              }
            />
          </div>
          <div className="form-group">
            <label htmlFor="interval_max">最大间隔（秒）</label>
            <input
              id="interval_max"
              type="number"
              min="1"
              max="600"
              value={settings.polling_interval_max}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  polling_interval_max: parseInt(e.target.value) || 30,
                })
              }
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="轮询默认启动时间">
        <p className="section-description">
          设置任务派发后，轮询在多长时间后启动。例如，设置为 2 分 30 秒，则任务 Prompt 被拷贝后，系统会等待 2 分 30 秒才开始检查输出文件。这样可以给 Agent 充足的时间生成结果文件。
        </p>
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="delay_min">延迟分钟数</label>
            <input
              id="delay_min"
              type="number"
              min="0"
              max="60"
              value={settings.polling_start_delay_minutes}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  polling_start_delay_minutes: parseInt(e.target.value) || 0,
                })
              }
            />
          </div>
          <div className="form-group">
            <label htmlFor="delay_sec">延迟秒数</label>
            <input
              id="delay_sec"
              type="number"
              min="0"
              max="59"
              value={settings.polling_start_delay_seconds}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  polling_start_delay_seconds: parseInt(e.target.value) || 0,
                })
              }
            />
          </div>
        </div>
      </SectionCard>

      <div className="action-bar">
        <button
          className="btn btn-primary"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? '保存中...' : '保存设置'}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => navigate('/projects')}
          disabled={saving}
        >
          返回
        </button>
      </div>
    </div>
  );
}
