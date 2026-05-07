import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import SectionCard from '../components/SectionCard';
import { api, extractApiErrorDetail } from '../api/client';

interface OAuthStartResponse {
  auth_url: string;
  session_id: string;
  redirect_uri: string;
}

interface CodexAgentStatus {
  authenticated: boolean;
  last_usage?: unknown;
  last_usage_error?: string;
}

interface OAuthExchangeResponse extends CodexAgentStatus {
  email?: string;
  plan_type?: string;
  chatgpt_account_id?: string;
  expires_at?: string;
}

function extractOAuthState(authUrl: string) {
  try {
    return new URL(authUrl).searchParams.get('state') || '';
  } catch {
    return '';
  }
}

export default function CodexAgentLoginPage() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const [authUrl, setAuthUrl] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [oauthState, setOauthState] = useState('');
  const [codeInput, setCodeInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [exchanging, setExchanging] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!agentId) {
      setError('缺少智能体 ID');
      setLoading(false);
      return;
    }
    api.post<OAuthStartResponse>(`/api/codex-usage/agents/${agentId}/oauth/start`, {
      return_url: `${window.location.origin}/agents`,
    })
      .then((result) => {
        setAuthUrl(result.auth_url);
        setSessionId(result.session_id);
        setOauthState(extractOAuthState(result.auth_url));
      })
      .catch((err) => setError(extractApiErrorDetail(String(err)) || '生成 Codex 登录链接失败'))
      .finally(() => setLoading(false));
  }, [agentId]);

  useEffect(() => {
    if (!agentId) return undefined;
    const timer = window.setInterval(() => {
      api.get<CodexAgentStatus>(`/api/codex-usage/agents/${agentId}/status`)
        .then((status) => {
          if (status.authenticated) {
            navigate('/agents', { replace: true });
          }
        })
        .catch(() => {});
    }, 2500);
    return () => window.clearInterval(timer);
  }, [agentId, navigate]);

  async function handleExchange(e: React.FormEvent) {
    e.preventDefault();
    if (!agentId || !sessionId || !codeInput.trim()) return;
    setExchanging(true);
    setError('');
    setMessage('');
    try {
      await api.post<OAuthExchangeResponse>(`/api/codex-usage/agents/${agentId}/oauth/exchange`, {
        session_id: sessionId,
        code: codeInput.trim(),
        state: oauthState || undefined,
      });
      setMessage('Codex 登录完成，正在返回智能体页面...');
      window.setTimeout(() => navigate('/agents', { replace: true }), 700);
    } catch (err) {
      setError(extractApiErrorDetail(String(err)) || 'Codex 授权码兑换失败');
    } finally {
      setExchanging(false);
    }
  }

  return (
    <div className="page">
      <PageHeader title="Codex 登录">
        <Link className="btn btn-secondary" to="/agents">返回智能体</Link>
      </PageHeader>

      {error && <div className="error-message">{error}</div>}
      {message && <div className="success-message">{message}</div>}

      <SectionCard title="OpenAI 授权">
        {loading ? (
          <div className="page-loading compact">正在生成登录链接...</div>
        ) : authUrl ? (
          <div className="codex-oauth-form">
            <label>
              授权链接
              <input value={authUrl} readOnly />
            </label>
            <div className="codex-actions codex-actions-compact">
              <a className="btn btn-primary codex-token-link" href={authUrl} target="_blank" rel="noreferrer">
                打开授权链接
              </a>
            </div>
            <form className="codex-oauth-form" onSubmit={handleExchange}>
              <label>
                授权回调链接或 code
                <textarea
                  value={codeInput}
                  onChange={(e) => setCodeInput(e.target.value)}
                  rows={4}
                  placeholder="http://localhost:1455/auth/callback?code=...&state=..."
                />
              </label>
              <button className="btn btn-primary" type="submit" disabled={exchanging || !codeInput.trim() || !sessionId}>
                {exchanging ? '兑换中...' : '完成登录'}
              </button>
            </form>
          </div>
        ) : (
          <p className="codex-note">登录链接不可用。</p>
        )}
      </SectionCard>
    </div>
  );
}
