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
  task_timeout_minutes: number;
}

interface PromptSettings {
  co_location_guidance: string;
  default_co_location_guidance: string;
}

const FEISHU_NOTIFY_EVENT_LABELS: Record<string, string> = {
  completed: '任务完成',
  timeout: '任务超时',
  error: '任务报错',
  project_completed: '项目完成',
};
const FEISHU_NOTIFY_EVENT_KEYS = Object.keys(FEISHU_NOTIFY_EVENT_LABELS);

interface FeishuSettings {
  webhook_url: string;
  notify_events: string[];
}

export default function ProjectSettingsPage() {
  const navigate = useNavigate();
  const isAdmin = isAdminUser();
  const [settings, setSettings] = useState<PollingSettings | null>(null);
  const [promptSettings, setPromptSettings] = useState<PromptSettings | null>(null);
  const [feishuSettings, setFeishuSettings] = useState<FeishuSettings>({ webhook_url: '', notify_events: [] });
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
    Promise.all([
      api.get<PollingSettings>('/api/settings/polling'),
      api.get<PromptSettings>('/api/settings/prompt'),
      api.get<FeishuSettings>('/api/settings/feishu'),
    ])
      .then(([polling, prompt, feishu]) => {
        setSettings(polling);
        setPromptSettings(prompt);
        setFeishuSettings(feishu);
      })
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
    if (s.task_timeout_minutes < 1 || s.task_timeout_minutes > 120) {
      return 'Task 超时时间必须在 1-120 分钟之间';
    }
    if (!promptSettings?.co_location_guidance.trim()) {
      return '同机分配引导不能为空';
    }
    return null;
  }

  async function handleSave() {
    if (!settings || !promptSettings) return;

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
      const savedPrompt = await api.put<PromptSettings>('/api/settings/prompt', {
        co_location_guidance: promptSettings.co_location_guidance,
      });
      setPromptSettings(savedPrompt);
      await api.put<FeishuSettings>('/api/settings/feishu', feishuSettings);
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

  if (!settings || !promptSettings) {
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

      <SectionCard title="默认 Task 超时时间">
        <p className="section-description">
          Task 运行超过此时间后，系统将标记为需要关注状态。
        </p>
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="task-timeout">超时时间（分钟）</label>
            <input
              id="task-timeout"
              type="number"
              min="1"
              max="120"
              value={settings.task_timeout_minutes}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  task_timeout_minutes: parseInt(e.target.value) || 10,
                })
              }
            />
            <div className="helper-text">范围：1-120 分钟</div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Prompt 设置">
        <p className="section-description">
          配置规划 Prompt 中关于同服务器 Agent 分配策略的引导文案。该内容会加入每次新生成的规划 Prompt。
        </p>
        <div className="form-group">
          <label htmlFor="co-location-guidance">同机分配引导</label>
          <textarea
            id="co-location-guidance"
            rows={10}
            value={promptSettings.co_location_guidance}
            onChange={(e) =>
              setPromptSettings({
                ...promptSettings,
                co_location_guidance: e.target.value,
              })
            }
          />
          <div className="helper-text">
            不能为空。保存后会作为纯文本加入规划 Prompt，位于参与 Agent 说明之后、输出要求之前。
          </div>
        </div>
        <div className="prompt-settings-actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() =>
              setPromptSettings({
                ...promptSettings,
                co_location_guidance: promptSettings.default_co_location_guidance,
              })
            }
            disabled={saving}
          >
            恢复默认值
          </button>
        </div>
      </SectionCard>

      <SectionCard title="飞书通知">
        <p className="section-description">
          配置飞书自定义机器人 Webhook，当任务或项目状态发生关键变化时，自动推送卡片通知。Webhook URL
          格式：https://open.feishu.cn/open-apis/bot/v2/hook/&lt;token&gt;
        </p>
        <div className="form-group">
          <label htmlFor="feishu-webhook-url">Webhook URL</label>
          <input
            id="feishu-webhook-url"
            type="url"
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
            value={feishuSettings.webhook_url}
            onChange={(e) =>
              setFeishuSettings({ ...feishuSettings, webhook_url: e.target.value })
            }
          />
          <div className="helper-text">留空则不发送飞书通知。</div>
        </div>
        <div className="form-group">
          <label>通知事件</label>
          <div className="checkbox-group">
            {FEISHU_NOTIFY_EVENT_KEYS.map((key) => (
              <label key={key} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={feishuSettings.notify_events.includes(key)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...feishuSettings.notify_events, key]
                      : feishuSettings.notify_events.filter((k) => k !== key);
                    setFeishuSettings({ ...feishuSettings, notify_events: next });
                  }}
                />
                {FEISHU_NOTIFY_EVENT_LABELS[key]}
              </label>
            ))}
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
