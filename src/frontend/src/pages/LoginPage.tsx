import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

const PASSWORD_REGEX = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$/;

function validatePassword(pw: string): string | null {
  if (pw.length < 6) return '密码至少需要6位';
  if (!/[a-z]/.test(pw)) return '密码需要包含小写字母';
  if (!/[A-Z]/.test(pw)) return '密码需要包含大写字母';
  if (!/\d/.test(pw)) return '密码需要包含数字';
  return null;
}

export default function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!username.trim()) {
      setError('请输入用户名');
      return;
    }

    if (mode === 'register') {
      if (username.trim().length < 2) {
        setError('用户名至少需要2个字符');
        return;
      }
      const pwError = validatePassword(password);
      if (pwError) {
        setError(pwError);
        return;
      }
      if (password !== confirmPassword) {
        setError('两次输入的密码不一致');
        return;
      }
    }

    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const result = await api.post<{ token: string }>(endpoint, {
        username: username.trim(),
        password,
      });
      localStorage.setItem('token', result.token);
      navigate('/projects');
    } catch (err: any) {
      const msg = err?.message || '';
      if (msg.includes('409')) {
        setError('该用户名已被注册');
      } else if (msg.includes('401')) {
        setError('用户名或密码错误');
      } else if (msg.includes('422')) {
        setError('输入格式不正确，请检查用户名和密码');
      } else {
        setError(mode === 'login' ? '登录失败，请检查用户名和密码。' : '注册失败，请稍后重试。');
      }
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setMode(mode === 'login' ? 'register' : 'login');
    setError('');
    setConfirmPassword('');
  }

  const isRegister = mode === 'register';
  const pwHint = isRegister && password.length > 0 ? validatePassword(password) : null;

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>HALF</h1>
        <p className="login-subtitle">Human-AI Loop Framework</p>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoFocus
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">{isRegister ? '设置密码' : '密码'}</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegister ? '大小写字母 + 数字，至少6位' : '请输入密码'}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
            />
            {pwHint && <div className="field-hint">{pwHint}</div>}
          </div>
          {isRegister && (
            <div className="form-group">
              <label htmlFor="confirmPassword">确认密码</label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="请再次输入密码"
                autoComplete="new-password"
              />
            </div>
          )}
          {error && <div className="error-message">{error}</div>}
          <button
            type="submit"
            className="btn btn-primary btn-full"
            disabled={loading}
          >
            {loading ? (isRegister ? '注册中...' : '登录中...') : (isRegister ? '注册' : '登录')}
          </button>
        </form>
        <div className="login-switch">
          {isRegister ? (
            <span>已有账号？<button type="button" className="link-btn" onClick={switchMode}>去登录</button></span>
          ) : (
            <span>没有账号？<button type="button" className="link-btn" onClick={switchMode}>注册新用户</button></span>
          )}
        </div>
      </div>
    </div>
  );
}
